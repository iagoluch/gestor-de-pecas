# Paleta de estados — maquete do apontamento (12/11/2026)

Decisão do usuário: usar **as cores que já existem no sistema**, sem criar hex novo.
Uma cor por estado; tudo que é ligado a um estado (faixa de status, botão, aviso, etiqueta) usa a cor dele.

| Estado / sistema   | Hex       | Origem no sistema                                   | Texto por cima |
|--------------------|-----------|-----------------------------------------------------|----------------|
| Produção           | `#15803d` | `--fill-producing` (`tokens.css`)                   | branco         |
| Setup              | `#0e7490` | `--fill-setup`; destaque `#3fd4ef` (`--state-setup` escuro) | branco |
| Parada             | `#c81e2c` | `--fill-stopped`                                    | branco         |
| Parada planejada   | `#fb923c` | `.status-row--parada_planejada` (`global.css:2121`) | escuro         |
| Retrabalho         | `#7a2f00` | `--fill-rework`; destaque `#ffb37a`                 | branco         |
| Sem apontamento    | `#f59e0b` | `--fill-waiting`                                    | escuro `#0b1a33` |
| Fora de turno      | `#5a6a85` | `--fill-neutral`                                    | branco         |
| Alerta (sistema)   | `#fbbf24` | `--warning` (tema escuro)                           | escuro         |
| Crítico (sistema)  | `#c81e2c` | `--fill-stopped`                                    | branco         |
| Ok (sistema)       | `#15803d` | `--fill-producing`                                  | branco         |

Botões de ação (iguais ao `.operator-action--*` de hoje):
- Iniciar verde, Parada vermelho, Setup petróleo, Retrabalho marrom.
- **Finalizar âmbar `#f59e0b` com texto escuro** (`.operator-action--finish`), inclusive o "Confirmar" do popup de finalizar.
- "Finalizar Setup" e "Finalizar Ret." usam a cor do estado que encerram.
- Azul `#0a63e8` fica só em "Carregar roteiro" e no "você está aqui" do roteiro.

## O que o sistema ainda não tem (NÃO construído)

- O Andon pinta a parada planejada com o âmbar de "sem apontamento" (`andon.css` 289, 903, 1080, 1193; `global.css:638`). Os dois estados ficam iguais na TV. Se for padronizar, o laranja `#fb923c` já existe em `global.css:2121`.
- Finalizar e Sem apontamento dividem o mesmo âmbar. Isso já é assim hoje e foi mantido a pedido.
- Andon roda em Chrome 79: só cor sólida nos estados (sem `color-mix`).
