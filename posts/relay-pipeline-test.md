---
title: "Test pipeline relay: come funziona la pubblicazione"
slug: "relay-pipeline-test"
meta_description: "Post di test per verificare la pipeline routine -> GitHub -> relay -> WP -> Telegram. Da eliminare dopo la conferma."
categories: ["Blog"]
tags: ["test"]
target_keyword: "test pipeline"
language: "it"
---

Questo e' un post di test per verificare la pipeline end-to-end della SEO content engine. Se vedi questo post come bozza su polara-ai.com e ricevi una preview Telegram, l'intera catena funziona.

## Cosa stiamo verificando

Il flusso e' questo: il routine schedula la generazione, scrive il file in posts/, fa push su GitHub. Il webhook fira il relay su Railway, che chiama il plugin polara-seo-bridge per creare la bozza WP, poi manda la preview su Telegram.

## Prossimi passi

Se questo test funziona, eliminiamo questo post da posts/ e dalla bozza WP. Dopodiche' configuriamo il vero ciclo settimanale.

## Domande frequenti

### Come elimino questo post di test?

Cancella il file posts/relay-pipeline-test.md dal repo e poi cancella la bozza dal pannello WP admin.

### Il relay e' pronto?

Si', e' attivo su Railway con il webhook configurato.

<script type="application/ld+json">{"@context":"https://schema.org","@type":"Article","headline":"Test pipeline relay","description":"Test post.","author":{"@type":"Organization","name":"Polara AI"},"datePublished":"2026-04-27","inLanguage":"it"}</script>
<script type="application/ld+json">{"@context":"https://schema.org","@type":"BreadcrumbList","itemListElement":[{"@type":"ListItem","position":1,"name":"Home","item":"https://polara-ai.com/"},{"@type":"ListItem","position":2,"name":"Blog","item":"https://polara-ai.com/blog/"},{"@type":"ListItem","position":3,"name":"Test","item":"https://polara-ai.com/relay-pipeline-test/"}]}</script>
<script type="application/ld+json">{"@context":"https://schema.org","@type":"FAQPage","mainEntity":[{"@type":"Question","name":"Test?","acceptedAnswer":{"@type":"Answer","text":"Si."}}]}</script>
