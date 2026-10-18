# Entrega 1 — Geração de explicações (regras de negócio) a partir das parametrizações

Autor: João Vitor Fernandes Ferreira · Disciplina SMA (INF0373A_BSI)

## O que há neste pacote
- `explicacoes/`: um arquivo Markdown para cada arquivo .gobr ({n_arquivos} arquivos), com uma tabela Nome | Condição | Frequência | Observação por regra, no formato dos exemplos do professor.
- `explicacoes_consolidado.md`: todas as explicações em um só arquivo, com sumário.
- `codigo/`: código do gerador, para leitura.
<!-- IF tem_polimento -->
- `explicacoes_polidas/`: as mesmas explicações com a redação de Condição e Observação reescrita por modelo de linguagem, sob validação (ver abaixo), e `polimento_diff.md`, com cada alteração antes e depois.
<!-- ENDIF -->

## Como as explicações foram geradas
A base da geração é determinística, para garantir fidelidade ao código:
1. O parser lê cada .gobr e separa time, carteira e blocos `parametros`, preservando a ordem. A ordem importa: cliente já parametrizado por uma regra anterior não é reprocessado pelas seguintes (manual, seção 7.6).
2. Cada condição é decomposta em átomos e traduzida por um glossário com fonte no manual (PDF e página). Condição que o manual não define mantém o texto original, com aviso.
3. As faixas de recência são calculadas pela ordem dos blocos: "recência em 90 dias" logo depois de "em 60 dias" significa, na prática, "entre 60 e 90 dias".
4. Há uma linha por bloco `parametros`, na ordem do código. Regras `nao agendar` são linhas próprias com Frequência "Não agendar".
<!-- IF tem_polimento -->

## Polimento da redação (controlado)
Sobre o esqueleto determinístico, um modelo de linguagem ({modelo_polimento}) reescreve apenas as colunas Condição e Observação em linguagem de negócio mais natural. O modelo não escreve do zero nem decide significado:
- Nome e Frequência não passam pelo modelo; os avisos ⚠ são copiados literalmente; os textos entre aspas das condições são trocados por marcadores antes do envio e restaurados depois.
- Cada reescrita é validada automaticamente: mesmos números, mesmos marcadores de relação (até, entre, mais de, fora, sem, exceto, não), mesmos qualificadores, vocabulário limitado ao do projeto, sem palavras de borda. Um segundo passo do modelo verifica a equivalência de sentido.
- A reescrita que falha em qualquer validação é descartada, e fica o texto determinístico.
- Resultado: {n_polidas} de {n_linhas_polidaveis} linhas reescritas; {n_fallback} mantiveram o texto determinístico.
- Entregamos as duas versões: `explicacoes/` (determinística) e `explicacoes_polidas/`.
<!-- ENDIF -->

## Como ler a tabela
- "Todos os clientes do escopo" / "Demais clientes do escopo": bloco sem condição; recebe os clientes não tratados pelas regras anteriores.
- "exceto clientes bloqueados nas regras 'Não agendar' acima": os bloqueios anteriores têm precedência.
- ⚠ indica ambiguidade ou condição sem definição no manual.

## Exemplo
Explicação gerada para um dos exemplos do professor:

{exemplo_gold}

## Limites conhecidos
- O manual não define se os extremos de uma faixa (por exemplo, 60 dias) estão incluídos. As explicações repetem os números do código sem afirmar a borda.
- `sem venda` ({n_sem_venda} blocos): leitura inferida ("provavelmente nunca compraram"); o manual cita apenas `sem venda ou prospects`.
- `fora da recencia ... entre a e b` ({n_fora_entre} blocos): pelo manual significa fora do intervalo; vários exemplos parecem usá-lo com o sentido de "dentro de a–b". A explicação traz o sentido literal com aviso.
- O manual não define se cliente sem nenhuma compra é alcançado por `fora da recencia`. Quando um bloco de prospects vem depois de um bloco assim, há aviso.
- {n_sem_entrada} blocos têm condição sem definição no manual; o texto original é mantido com aviso.
- Arquivos com problema de sintaxe têm aviso no topo: parêntese aberto e bloco sem frequência em um arquivo (a tabela pode estar incompleta), `version 1.0` ausente, aspa solta e caractere de controle em outros.
- Requisitos que os exemplos descrevem mas o GOBR não representa (capacidade de 35 clientes por dia no Maxlub; "agendar inadimplentes" no V1 Vidros) ficam fora da tabela.

## Verificações
- Checagens automáticas por arquivo: número de linhas da tabela igual ao número de blocos; frequência escrita igual à frequência lida do código (nova leitura independente); todo número citado existe no código. Resultado: {n_falhas} falhas em {n_arquivos} arquivos.
- Comparação com os três exemplos do professor (Infinitto, Maxlub, V1 Vidros): faixas e frequências coincidem. As diferenças encontradas são bloqueios presentes no código mas ausentes da descrição, o fallback do Maxlub e os dois requisitos citados acima.
- Suíte de testes automatizados (pytest).

## Como reproduzir
Requer Python {python_requer} (ver pyproject.toml). A partir da pasta codigo/, instale com `pip install -e .`.

Coloque os .gobr em `data/gobr/` e rode `python scripts/gerar_explicacoes.py`.
