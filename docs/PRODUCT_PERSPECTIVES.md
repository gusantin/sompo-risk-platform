# Perspectivas de apresentação

Na Vercel, as perspectivas usam a captura publicável incluída no frontend quando não há backend disponível. Cadastro fica desabilitado com explicação; o Copilot oferece resumo determinístico do contexto armazenado, sem interpretação por IA. Veja [configuração e limites do deploy](VERCEL_PRESENTATION.md). O fluxo de cadastro descrito abaixo é local, em development/test.

`/seguradora` apresenta três clientes fictícios, prioridades, detalhe do cliente e suas propriedades. `?cliente=Cliente+A&fazenda=demo_portfolio_confresa` mantém o detalhe dentro da experiência da seguradora.

`/segurado` representa somente Cliente A, com Fazenda Araguaia (Confresa/MT) e Fazenda Horizonte (Sorriso/MT). `?fazenda=demo_portfolio_horizonte` preserva a seleção. A troca atualiza os componentes locais, mapa e Copilot sem recarregar o documento; voltar/avançar também restaura a seleção. Sem seleção, o Copilot compara as duas fazendas; com seleção, consulta apenas aquela fazenda.

As identidades não representam segurados SOMPO. Cliente A agora identifica Araguaia; Cliente B identifica Pantanal Norte; Cliente C permanece Campo Sul. Os IDs das propriedades não mudaram. Não há índice de risco duplicado no frontend. Todos os valores vêm de `data/presentation_portfolio.json`, processado pelo serviço e pela projeção existentes de EnvironmentalContext. A atualização pode mudar os resultados. Não se preservam artificialmente cores ou scores antigos.

## Captura e cadastro

`python -m scripts.capture_product_perspectives` atualiza as propriedades existentes e tenta Sorriso, Lucas do Rio Verde e Rondonópolis, nessa ordem, interrompendo na primeira resposta ambiental válida. Usa IBGE e os mesmos provedores/motores existentes. Não envia Telegram nem grava no Firebase.

Adicionar fazenda solicita nome, município e UF. `PropriedadeService.criar_demonstrativa` valida e salva a identidade no mesmo dataset demonstrativo, com `score: null`, estado `waiting` e sem coordenadas inventadas. Uma segunda requisição resolve município/UF no IBGE e chama a captura ambiental existente. Não há score antes do motor determinístico. Falhas deixam a fazenda salva, sem inventar evidências; o usuário pode tentar consultar novamente. Capturas posteriores preservam propriedades adicionais. A gravação usa a substituição atômica existente; alterações de cadastro/análise são serializadas no processo local de apresentação.

O cadastro demonstrativo só está habilitado em development/test. Estas rotas não oferecem um modo autenticado de segurado real: a autenticação existente é de aplicação, por API key, sem vínculo de usuário a cliente. O cadastro real existente (`POST /fazendas`, `PropriedadeService.criar`, Firestore e análise por propriedade) permanece intacto, com seus campos e validações. Não se encaminham identidades demonstrativas para esse caminho. Vincular uma sessão real a um cliente e habilitar esse cadastro na experiência do segurado exige o futuro auth/RBAC; não se interpreta uma API key como identidade de segurado.

## Escopo e limites de segurança

O seletor é de apresentação/desenvolvimento, não autenticação. `/showcase/perspectives/segurado` fixa Cliente A no servidor, mesmo se o chamador fornecer outro cliente. O BFF de dados, o HTML/RSC, a seleção, os mapas e o Copilot recebem somente as propriedades desse escopo. O BFF do Copilot força perspectiva/mode e ignora tentativas do corpo de mudar o cliente segurado; um ID de outra propriedade é rejeitado pelo backend. A visão da seguradora pode consultar toda a carteira ou um cliente.

Isso é isolamento de respostas por perspectiva, não isolamento de tenant autenticado. As URLs da seguradora e APIs de aplicação existentes continuam acessíveis no ambiente de demonstração segundo as regras anteriores. Não publicar como portal de clientes antes de implementar identidade/RBAC nos endpoints e BFFs.

Os links entre perspectivas não fazem prefetch, evitando carregar antecipadamente respostas da seguradora enquanto o usuário permanece na experiência do segurado.

Alertas e entregas são consultados pelos serviços existentes e pela propriedade exata. A apresentação mostra aberto/reconhecido/resolvido e o estado real da entrega, ou informa que não foram consultados. Nenhum status de entrega é inferido a partir do risco. Máquinas e histórico permanecem explicitamente indisponíveis quando ausentes da captura. A UI não mostra IDs de alertas, notificações ou outbox ao segurado. O Copilot segue somente leitura. Os motores, política de notificação, lifecycle, outbox, dispatcher e deduplicação não foram alterados.

Consultas de snapshot são apresentadas como cache, com timestamps originais; leituras vencidas são marcadas como desatualizadas. Previsões conservam suas janelas e disponibilidade; avisos INMET e detecções INPE mantêm sua semântica. Coordenadas são pontos municipais, não a localização real de uma fazenda. A notificação externa usa a identidade da propriedade; `telegram_demo --portfolio-client A --preview` agora seleciona Araguaia, sem enviar mensagem.

## Verificação

Backend: `python -m unittest tests.test_product_perspectives tests.test_copilot_portfolio tests.test_telegram_portfolio tests.test_presentation_portfolio` e suíte completa.

Browser: `node scripts/perspective-check.mjs` no frontend, com `FRONTEND_URL` apontando à instância de teste. Valida dados/BFF/Copilot, seleção, mapa e as duas rotas em 390, 1366, 1440 e 1920 pixels. O teste do formulário intercepta respostas para não alterar a captura real; persistência e integração são exercitadas pelos testes de backend com fixtures isoladas.
