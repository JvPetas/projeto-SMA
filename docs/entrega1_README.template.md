# Entrega 1 — Geração de explicações (regras de negócio) a partir das parametrizações

Autor: João Vitor Fernandes Ferreira · Disciplina SMA (INF0373A_BSI)

## O que há neste pacote
- `explicacoes/`: um arquivo Markdown para cada arquivo .gobr ({n_arquivos} arquivos), com uma tabela Nome | Condição | Frequência | Observação por regra, no formato dos exemplos do professor.
- `explicacoes_consolidado.md`: todas as explicações em um só arquivo, com sumário.
- `codigo/`: código do gerador, para leitura.

## Como as explicações foram geradas
A base da geração é determinística, para garantir fidelidade ao código:
1. O parser lê cada .gobr e separa time, carteira e blocos `parametros`, preservando a ordem. A ordem importa: cliente já parametrizado por uma regra anterior não é reprocessado pelas seguintes (manual, seção 7.6).
2. Cada condição é decomposta em átomos e traduzida por um glossário com fonte no manual (PDF e página). Condição que o manual não define mantém o texto original, com aviso.
3. As faixas de recência são calculadas pela ordem dos blocos: "recência em 90 dias" logo depois de "em 60 dias" significa, na prática, "entre 60 e 90 dias".
4. Há uma linha por bloco `parametros`, na ordem do código. Regras `nao agendar` são linhas próprias com Frequência "Não agendar".

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
- A tabela descreve os blocos do código; requisitos exclusivos da descrição humana não criam linhas adicionais.

## Decisões de projeto

Reescrita por modelo de linguagem: avaliamos reescrever a coluna Condição com um modelo de linguagem sob validação automática (números, relações, qualificadores, acentos, parênteses e verificação independente). Na primeira iteração, 7 de 20 linhas dos exemplos de referência foram alteradas e todas pioraram o texto: todas removeram os parênteses que marcam o escopo e uma também perdeu um acento. Na segunda iteração, com os validadores corrigidos, 1 de 20 foi aceita, com mudança apenas de maiúscula, e 15 foram rejeitadas pelo verificador independente (os validadores determinísticos não rejeitaram nenhuma). Por isso a entrega mantém somente o texto determinístico, que não depende de modelo e é reproduzível.

<!-- IF notas_gabarito -->
## Divergências entre a descrição e o código nos exemplos de referência

{notas_gabarito}
<!-- ENDIF -->

## Verificações
- Checagens automáticas por arquivo: número de linhas da tabela igual ao número de blocos; frequência escrita igual à frequência lida do código (nova leitura independente); todo número citado existe no código. Resultado: {n_falhas} falhas em {n_arquivos} arquivos.
- Comparação com os exemplos do professor por faixa e frequência; divergências documentadas são reportadas separadamente.
- Suíte de testes automatizados (pytest).

## Como reproduzir
Requer Python {python_requer} (ver pyproject.toml). A partir da pasta codigo/, instale com `pip install -e .`.

Coloque os .gobr em `data/gobr/` e rode `python scripts/gerar_explicacoes.py`.
