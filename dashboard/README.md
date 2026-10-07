# Dashboard de supervision

HTML + JS + Chart.js (copie locale dans `vendor/`, fonctionne sans internet). Servi par l'API : http://localhost:8000
Une seule page HTML, cinq vues par routage `#/…`, un seul WebSocket partagé, bandeau d'état visible partout.

| Onglet | Route | Contenu |
|---|---|---|
| Vue d'ensemble | `#/` | température, humidité, gaz (maintenant, prévu à +10 min, tendance, petite courbe ; seuil informatif pour la température seulement), état de l'analyse IA, commandes buzzer / voyant, 3 dernières alarmes non acquittées, vignette caméra |
| Capteurs | `#/capteurs` | une fiche par capteur (DHT22, MQ-2, PIR) : photo `img/*.png`, valeur, santé, mise en/hors service, courbe 1 h + prévision ; le détail (branchement, lectures ratées, min/moy/max…) est replié sous « Détails ». Fiche actionneurs : photo et état |
| Caméra | `#/camera` | flux en direct, temps d'inférence (objectif < 100 ms), personnes, galerie des captures d'intrusion |
| Alarmes | `#/alarmes` | journal complet, filtre « non acquittées », acquittement |
| Système | `#/systeme` | état des services (+ une ligne sur le boîtier), journal des actions |

## Fichiers
- `index.html`, `style.css` : structure et thème (IHM industrielle, couleur réservée aux états anormaux)
- `js/core.js` : API, WebSocket, état partagé, bandeau, composants communs (`SX`)
- `js/pages/*.js` : une page par fichier (`init`, `show`, `hide` ; les sondages ne tournent que sur la page affichée)
- `js/app.js` : routeur

Le dossier est monté en lecture seule dans le conteneur de l'API : une modification est visible en rechargeant la page, sans rebuild.
