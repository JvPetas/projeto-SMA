"""Levantamento determinístico e somente leitura do corpus e do manual.

Execute com python -B scripts/survey_duvidas.py SECAO.
Não escreve saídas em disco, não usa rede, Git ou modelos de linguagem.
Grupos seguem a chave literal de escopos do analisador existente; não se
presume equivalência de carteiras, times ou qualificadores de recência.
"""
import argparse
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from gobr_agent.parsing import parse_dir
from gobr_agent.parsing.models import Parametros
from gobr_agent.parsing.normalize import normalizar
from gobr_agent.explain.atomos import separar_atomos
from gobr_agent.explain.recencia import (
    _classificar, analisar_grupo, chave_do_grupo, intersecao, INF,
)

DATA = ROOT / "data/gobr"
REC = re.compile(r"(?P<fora>fora da )?recencia de (?P<tipo>positivacao|visita)(?: (?P<qual>global|do vendedor))? (?:em (?P<n>\d+) dias?|entre (?P<a>\d+) dias? e (?P<b>\d+) dias?)")


def cond(p):
    return " ".join((c.conector + " " if c.conector else "") + c.texto for c in p.quando)


def freq(p):
    return "nao agendar" if p.nao_agendar else p.frequencia.bruta if p.frequencia else "SEM FREQUENCIA"


def ref(a, p):
    return f"{a.caminho}:{p.linha_ini}"


def groups(a):
    result = defaultdict(list)
    for p in a.parametros:
        result[chave_do_grupo(p)].append(p)
    return result


def atoms(p):
    return [x for c in p.quando for x in separar_atomos(c.texto)]


def show(a, p):
    print(ref(a, p), repr(p.nome), "|", cond(p), "|", freq(p))


def baseline(files):
    print("BASE", len(files), "arquivos", sum(len(a.parametros) for a in files), "parametros", sum(len(groups(a)) for a in files), "grupos literais")
    for other in [ROOT / "infos/referencias", ROOT.parent / "trabalho/referencias"]:
        different = [a.caminho for a in files if (other / a.caminho).exists() and (other / a.caminho).read_bytes() != (DATA / a.caminho).read_bytes()]
        common = sum((other / a.caminho).exists() for a in files)
        print("COPIA", str(other), "comuns", common, "diferentes", different)
    pdf = ROOT / "data/manual/govendas-rules.pdf"
    for other in [ROOT / "infos/govendas-rules.pdf", ROOT.parent / "trabalho/govendas-rules.pdf"]:
        print("PDF_IDENTICO", str(other), pdf.read_bytes() == other.read_bytes())


def sem_venda(files):
    default = []
    totals = defaultdict(list)
    names = defaultdict(list)
    definitions = []
    for a in files:
        for b in a.blocos:
            for c in getattr(b, "quando", ()):
                for x in separar_atomos(c.texto):
                    if re.match(r"sem vendas?\b", x):
                        totals[x].append((a.caminho, c.linha, b.nome))
                        if isinstance(b, Parametros):
                            for e in b.escopos:
                                for n in e.nomes:
                                    names[(e.tipo, n)].append(f"{a.caminho}:{c.linha}")
                        else:
                            definitions.append((a.caminho, b.rotulo, b.nome, c.linha, x))
        for p in a.parametros:
            if "regra padrao do govendas customizavel" in normalizar(p.nome) and "sem venda" in atoms(p):
                before = [q for q in a.parametros if q.linha_ini < p.linha_ini and chave_do_grupo(q) == chave_do_grupo(p)]
                default.append((a, p, all(any(t in atoms(q) for q in before) for t in ["ativos para o vendedor", "inativos para o vendedor"])))
    print("SEM_VENDA_TOTAIS")
    for x, hits in totals.items():
        print(x, len(hits), "atomos", len({h[0] for h in hits}), "arquivos")
    exact = [r for r in default if normalizar(r[1].nome) == 'regra padrao do govendas customizavel: frequencia de clientes sem vendas']
    print("PADRAO_NOME_EXATO", len(exact), "APOS_AMBOS", sum(x[2] for x in exact))
    print("PADRAO_INCLUINDO_VARIANTE", len(default), "sem venda", "APOS_AMBOS", sum(x[2] for x in default))
    print("ARQUIVOS_PADRAO", ",".join(a.caminho for a, _, _ in default))
    for target in ["regra_001.gobr", "regra_002.gobr", "regra_041.gobr"]:
        a = next(a for a in files if a.caminho == target)
        print("SEQUENCIA", target)
        for p in a.parametros:
            show(a, p)
    print("NOMES_ESCOPO", len(names), "pares arquivo/tipo/nome", len({(h.split(':')[0], k) for k, hs in names.items() for h in hs}))
    for (kind, n), hits in sorted(names.items()):
        print("DESTAQUE" if re.search("prospec|novo|primeira|potencial", normalizar(n)) else "NOME", kind, repr(n), ",".join(dict.fromkeys(hits)))
    print("DEFINICOES_DIRETAS", len(definitions))
    for hit in definitions:
        print(*hit, sep=" | ")
    highlighted=[]
    for a in files:
        for p in a.parametros:
            if any(re.match(r'sem vendas?\b',x) for x in atoms(p)) and re.search('prospec|novo|primeira|potencial',normalizar(p.nome)+' '+str(chave_do_grupo(p))):
                highlighted.append((a,p))
                print('BLOCO_DESTAQUE',ref(a,p),repr(p.nome),'ESCOPO',repr(chave_do_grupo(p)))
    print('DESTAQUES_BLOCOS',len(highlighted),'ARQUIVOS',len({a.caminho for a,p in highlighted}))
    print('NOMES_POR_TIPO',dict(Counter(kind for kind,n in names)))


def pairs(files):
    sets = {"positivos_mesma_qualificacao": [], "positivos_cadeia_existente": []}
    for a in files:
        for key, ps in groups(a).items():
            last_chain, last_exact = {}, {}
            for p in ps:
                cl = _classificar(p)
                if not cl:
                    continue
                aa = atoms(p)
                m = REC.fullmatch(aa[0]) if len(aa) == 1 else None
                if cl[0] in last_chain:
                    q, qm = last_chain[cl[0]]
                    if m and qm and not m['fora'] and not qm['fora']:
                        hi, lo = int(qm['n'] or qm['b']), int(m['a'] or 0)
                        sets['positivos_cadeia_existente'].append((hi, lo, a, q, p))
                exact = (cl[0], tuple(sorted(cl[2])))
                if exact in last_exact:
                    q, qm = last_exact[exact]
                    if m and qm and not m['fora'] and not qm['fora']:
                        hi, lo = int(qm['n'] or qm['b']), int(m['a'] or 0)
                        sets['positivos_mesma_qualificacao'].append((hi, lo, a, q, p))
                last_exact[exact] = (p, m)
                last_chain[cl[0]] = (p, m)
    for label, rows in sets.items():
        cat = lambda hi, lo: "N+1" if lo == hi + 1 else "N" if lo == hi else "OUTRO"
        print("PARES", label, len(rows), dict(Counter(cat(hi, lo) for hi, lo, *_ in rows)))
        second_between=[r for r in rows if ' entre ' in cond(r[4])]
        print('SEGUNDO_ENTRE',len(second_between),dict(Counter(cat(r[0],r[1]) for r in second_between)))
        em_entre=[r for r in second_between if ' em ' in cond(r[3])]
        print('EM_SEGUIDO_ENTRE',len(em_entre),dict(Counter(cat(r[0],r[1]) for r in em_entre)))
        for hi,lo,a,q,p in second_between:
            if cat(hi,lo)=='OUTRO':
                print('OUTRO_ENTRE',ref(a,q),cond(q),'->',ref(a,p),cond(p))
        for k in ["N+1", "N", "OUTRO"]:
            for hi, lo, a, q, p in [r for r in rows if cat(r[0], r[1]) == k][:5]:
                print(k, ref(a, q), cond(q), "->", ref(a, p), cond(p), "hi/lo", hi, lo)


def prospects(files):
    counts = Counter()
    pair_counts = Counter()
    for a in files:
        for key, ps in groups(a).items():
            pr = [p for p in ps if any("no ciclo de vida prospect" in x for x in atoms(p))]
            out = [p for p in ps if _classificar(p) and len(atoms(p)) == 1 and atoms(p)[0].startswith("fora da recencia")]
            if not pr or not out:
                continue
            before = any(p.linha_ini < o.linha_ini for p in pr for o in out)
            after = any(p.linha_ini > o.linha_ini for p in pr for o in out)
            counts["MISTO" if before and after else "ANTES" if before else "DEPOIS"] += 1
            for p in pr:
                for o in out:
                    pair_counts['ANTES' if p.linha_ini < o.linha_ini else 'DEPOIS'] += 1
            if after:
                print("DEPOIS_GRUPO", a.caminho, repr(key))
                for p in pr:
                    for o in out:
                        if o.linha_ini < p.linha_ini:
                            print("FORA", ref(a, o), repr(o.nome), "-> PROSPECT", ref(a, p), repr(p.nome))
    print("PROSPECT_GRUPOS", sum(counts.values()), dict(counts), "PARES", dict(pair_counts))


def merge_int(intervals):
    result = []
    for lo, hi in sorted(intervals):
        if hi < lo:
            continue
        if result and lo <= result[-1][1] + 1:
            result[-1] = (result[-1][0], max(result[-1][1], hi))
        else:
            result.append((lo, hi))
    return result


def int_intervals(p):
    """Hipótese explícita: dias inteiros, em/entre inclusivos, fora=complemento."""
    if not _classificar(p):
        return None
    result, quals = [(0, INF)], set()
    for x in atoms(p):
        m = REC.fullmatch(x)
        quals.add((m['tipo'], m['qual']))
        lo, hi = (0, int(m['n'])) if m['n'] else (int(m['a']), int(m['b']))
        it = [(0, lo-1), (hi+1, INF)] if m['fora'] else [(lo, hi)]
        result = merge_int((max(l1,l2), min(h1,h2)) for l1,h1 in result for l2,h2 in it)
    return quals, result


def coverage(files):
    counts, covered, full = Counter(), Counter(), []
    for a in files:
        for key, ps in groups(a).items():
            ca = [p for p in ps if p.catch_all]
            if ca:
                counts['catchall_qualquer'] += 1
                counts['catchall_agenda' if any(not p.nao_agendar for p in ca) else 'so_catchall_nao_agendar'] += 1
                if ps[-1].catch_all and ps[-1].nao_agendar:
                    counts['termina_fallback_nao_agendar'] += 1
                if any(p.depende_do_calendario for p in ca):
                    counts['catchall_temporal'] += 1
                continue
            counts['sem_ambos'] += 1
            chains = defaultdict(list)
            for p in ps:
                ci = int_intervals(p)
                if ci and len(ci[0]) == 1:
                    chains[next(iter(ci[0]))] += ci[1]
            cov = {str(k): merge_int(v) for k,v in chains.items()}
            ok = any(v == [(0, INF)] for v in cov.values())
            covered['cobre' if ok else 'nao_cobre'] += 1
            covered['com_recencia_pura' if chains else 'sem_recencia_pura'] += 1
            print("SEM_CATCHALL", a.caminho, repr(key), "LINHAS", ','.join(str(p.linha_ini) for p in ps), "COBRE" if ok else "NAO_COBRE", repr(cov))
            if ok:
                full.append((a.caminho, key))
    print("COBERTURA", dict(counts), "SEM_CATCHALL", dict(covered))


def empty(files):
    total = 0
    chosen = {"regra_155.gobr":77, "regra_221.gobr":44, "regra_003.gobr":58, "regra_135.gobr":74, "regra_226.gobr":39, "regra_179.gobr":71}
    for a in files:
        for key, ps in groups(a).items():
            classes = [_classificar(p) for p in ps]
            for i, (p, info) in enumerate(zip(ps, analisar_grupo(ps))):
                if not info.puro or info.efetivo != ():
                    continue
                total += 1
                print("VAZIO", ref(a,p), repr(p.nome), repr(classes[i]))
                if chosen.get(a.caminho) != p.linha_ini:
                    continue
                consumers = [q for j,q in enumerate(ps[:i]) if classes[j] and classes[j][0] == info.cadeia and intersecao(classes[j][1],info.intervalo)]
                raw = (DATA/a.caminho).read_text(encoding='utf-8-sig').splitlines()
                for q in consumers+[p]:
                    print("BRUTO", ref(a,q), "CLASS", repr(_classificar(q)), "INT_EXATO",repr(int_intervals(q)))
                    for ln in range(q.linha_ini,q.linha_fim+1):
                        print(f"{ln}: {raw[ln-1]}")
                    print("CONDICOES_PARSEADAS",[(c.linha,c.conector,c.texto) for c in q.quando])
    print("VAZIOS_TOTAL", total)


def numbers(files):
    hits=[]
    for a in files:
        for p in a.parametros:
            t=normalizar(p.nome)
            # Contagem literal, sem inferir intenção nem equivalência de bordas.
            nt=set(map(int,re.findall(r'\b(\d+)\s*(?:dias?\b|d\b)',t)))
            for m in re.finditer(r'\b(\d+)\s*(?:d(?:ias?)?)?\s*(?:a|e)\s*(\d+)\s*(?:dias?\b|d\b)',t):
                nt.update(map(int,m.groups()))
            nd=set(map(int,re.findall(r'\bdia\s+(\d+)\b',t)))
            # Só alegações explícitas de frequência, não frequência histórica.
            nf=set(map(int,re.findall(r'\b(?:frequencia|freq\.?)\s*(?:de\s*)?(\d+)\s*(?:dias?\b|d\b)',t)))
            nf.update(map(int,re.findall(r'(?:^|:\s*)(\d+)\s*(?:dias?\b|d\b)',t)))
            cf = set()
            if p.frequencia:
                if p.frequencia.dias is not None:
                    cf.add(p.frequencia.dias)
                cf.update(v for v in (p.frequencia.minimo_dias,p.frequencia.maximo_dias) if v is not None)
                cf.update(f.dias for f in p.frequencia.alternativas if f.dias is not None)
                cf.update(map(int,re.findall(r'\b(\d+)\s+dias?\b',p.frequencia.bruta)))
            ct=set(map(int,re.findall(r'\b(\d+)\s+dias?\b',cond(p)))) | cf
            cd=set()
            for f in p.filtros_temporais:
                if f.categoria=='dia_do_mes':
                    cd.update(int(v) for k,v in f.valor.items() if k in ['inicio','fim'] and isinstance(v,int))
            reasons=[]
            for kind,ns,cs in [('freq_explicita',nf,cf),('numero_temporal_ausente',nt,ct),('dia',nd,cd)]:
                if ns and not ns<=cs:
                    reasons.append((kind,sorted(ns),sorted(cs)))
            if reasons:
                hits.append((a,p,reasons))
    print('NUMEROS_DIVERGENCIAS_LITERAIS_CANDIDATAS',len(hits),'arquivos',len({a.caminho for a,p,r in hits}), 'RAZOES',dict(Counter(kind for a,p,rs in hits for kind,_,_ in rs)))
    for a,p,r in hits:
        print('DIVERGENCIA',ref(a,p),repr(p.nome),'|',cond(p),'|',freq(p),'|',[(f.linha,f.bruta) for f in p.filtros_temporais],'|',r)
    a=next(a for a in files if a.caminho=='regra_128.gobr')
    for p in a.parametros:
        if any('a partir do dia 16'==f.bruta for f in p.filtros_temporais):
            show(a,p)
            print('TEMPORAIS',[(f.linha,f.bruta) for f in p.filtros_temporais])


def ramo(files):
    counts=Counter()
    fs=defaultdict(set)
    for a in files:
        for b in a.blocos:
            for c in getattr(b,'quando',()):
                for x in separar_atomos(c.texto):
                    if not x.startswith('ramo de atividade igual('):
                        continue
                    vals=re.findall(r'"([^"]*)"',x)
                    kind='numerico' if vals and all(v.isdigit() for v in vals) else 'texto'
                    counts[kind]+=1
                    fs[kind].add(a.caminho)
                    print('RAMO',kind,f'{a.caminho}:{c.linha}',repr(x),'balance',x.count('(')-x.count(')'))
    print('RAMO_TOTAIS',dict(counts),'ARQUIVOS',{k:len(v) for k,v in fs.items()},'COM_TEXTO',sorted(fs['texto']))


def manual():
    import fitz
    d=fitz.open(ROOT/'data/manual/govendas-rules.pdf')
    for p in d:
        t=p.get_text()
        if re.search(r'padr[aã]o|indefinid|prospect|sem parametr|pelo menos|no m[ií]nimo|a partir|at[eé]|entre',t,re.I):
            print(f'=== PDF {p.number+1}; IMPRESSA {p.number-3} ===\n{t}')


def main():
    sys.stdout.reconfigure(encoding='utf-8')
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('section',choices=['base','sem_venda','pares','prospects','cobertura','vazios','numeros','ramo','manual'])
    args=ap.parse_args()
    funcs={'base':baseline,'sem_venda':sem_venda,'pares':pairs,'prospects':prospects,'cobertura':coverage,'vazios':empty,'numeros':numbers,'ramo':ramo}
    if args.section=='manual':
        manual()
    else:
        funcs[args.section](parse_dir(DATA))


if __name__=='__main__':
    main()
