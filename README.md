# J.A.R.V.I.S.

Assistente pessoal estilo Homem de Ferro: interface HUD, voz (ouvir e falar) e cérebro com Claude.

- Instalável no celular e no PC (PWA).
- Modo "Sempre ouvindo": com o app aberto, diga "Jarvis, ..." e ele responde.
- Ferramentas: hora, abrir sites, timers com aviso falado, notas, pesquisa na web, memória e visão da tela.
- "Bom dia, senhor": resumo falado do dia (clima, notícias, notas) na primeira abertura do dia.

Para usar fora do claude.ai, abra CONFIG e informe sua chave da API Anthropic (fica salva só no seu navegador).

## Controlar o PC (Windows)

Baixe e abra o [JarvisPonte.exe](https://github.com/pedrooriani9p-oss/jarvis/releases/download/ponte/JarvisPonte.exe).
Na primeira vez ele copia um código de pareamento: cole em CONFIG → "Código do PC" no Jarvis.
A ponte escuta só em 127.0.0.1, aceita apenas o site do Jarvis com o código, e tem uma lista fixa de ações
(abrir/fechar programas, volume, mídia, desligar/bloquear, print, pastas, procurar e abrir arquivos, digitar).
Para tirar da inicialização do Windows: `JarvisPonte.exe --remover`.

A ponte também ouve "Ei Jarvis" em segundo plano (openWakeWord, offline): traz a janela do Jarvis para frente e ele começa a ouvir o pedido. Dá para desligar em CONFIG.
