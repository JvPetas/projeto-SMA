"""Listagem sem rede, configuração local e saída sem credenciais."""
from types import SimpleNamespace

from scripts import listar_modelos as modelos


def test_separa_acoes_limites_e_dimensoes_sem_escolher(tmp_path, capsys):
    env = tmp_path / ".env"
    segredo = "credencial-ficticia-para-teste"
    env.write_text("GEMINI_API_KEY=" + segredo + "\n", encoding="utf-8")
    chamadas = []

    class Cliente:
        def __init__(self, **kwargs):
            assert kwargs["api_key"] == segredo
            self.models = self

        def list(self):
            chamadas.append("list")
            # Qualquer mensagem do cliente deve ser suprimida.
            print(segredo)
            return [SimpleNamespace(name="models/texto", supported_actions=["generateContent"],
                                    input_token_limit=80, output_token_limit=20),
                    {"name": "models/vetor", "supported_actions": ["embedContent"], "dimensions": [12, 24]},
                    {"name": "models/sem-dimensao", "supported_actions": ["embedContent"]},
                    {"name": "models/outro", "supported_actions": ["countTokens"]}]

        def close(self):
            chamadas.append("close")

    assert modelos.main(["--env", str(env)], client_factory=Cliente) == 0
    saida = capsys.readouterr().out
    assert segredo not in saida
    assert "models/texto | 80 | 20" in saida
    assert "models/vetor | 12, 24" in saida and "models/sem-dimensao | não informadas" in saida
    assert "models/outro" not in saida
    assert chamadas == ["list", "close"] and "Nenhum modelo escolhido" in saida


def test_ausencia_ou_chave_vazia_para_sem_cliente(tmp_path, capsys):
    p = tmp_path / ".env"
    def proibido(**kwargs):
        raise AssertionError("não criar cliente")
    assert modelos.main(["--env", str(p)], client_factory=proibido) == 1
    assert "ausente" in capsys.readouterr().out
    p.write_text("GEMINI_API_KEY=\n", encoding="utf-8")
    assert modelos.main(["--env", str(p)], client_factory=proibido) == 1
    assert "vazia" in capsys.readouterr().out


def test_erro_do_cliente_nao_expoe_segredo(tmp_path, capsys):
    p = tmp_path / ".env"
    segredo = "credencial-ficticia-sigilosa"
    p.write_text("GEMINI_API_KEY=" + segredo, encoding="utf-8")
    def falhar(**kwargs):
        print(segredo)
        raise RuntimeError("URL contendo " + segredo)
    assert modelos.main(["--env", str(p)], client_factory=falhar) == 1
    saida = capsys.readouterr()
    assert segredo not in saida.out + saida.err and "Falha ao listar" in saida.err
