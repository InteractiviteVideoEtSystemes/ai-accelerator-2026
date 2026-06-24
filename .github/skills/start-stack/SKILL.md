---
name: start-stack
description: >-
    Démarre l'intégralité de la stack locale du projet (Supabase CLI + Temporal +
    worker + frontend via `make up`), vérifie sa santé, et répare automatiquement
    tout composant défaillant. Le démarrage et le contrôle de santé sont délégués
    à des sous-agents Haiku ; le diagnostic et la réparation à un sous-agent Opus.
    À utiliser quand l'utilisateur demande de « démarrer la stack », « lancer le
    projet », « start the stack », ou de remettre la stack en état de marche.
user-invocable: true
---

# Démarrage + auto-réparation de la stack

Tu es l'**orchestrateur**. Tu ne fais pas le travail toi-même : tu délègues chaque
phase à un sous-agent via l'outil `task`, en imposant le **modèle** indiqué. Tu
boucles jusqu'à ce que la stack soit entièrement démarrée et saine, puis tu
t'arrêtes.

## Contexte de la stack

- Orchestrée par le `Makefile` à la racine du projet.
- `make up` exécute `supabase start` (Postgres + API/Kong + Auth + Storage +
  Studio, migrations + seed appliqués) **puis** `docker compose up -d` (Temporal,
  Temporal UI, worker, frontend).
- Prérequis : Docker Desktop en marche, et les CLI `supabase`, `make`, `docker`.
- Un fichier `.env` est requis ; le créer depuis `.env.example` s'il manque.
- Environnement Windows → utiliser PowerShell pour toutes les commandes.

### Services attendus et points de contrôle

| Service          | Conteneur / source        | Contrôle de santé (attendu)                |
| ---------------- | ------------------------- | ------------------------------------------ |
| Frontend         | `frontend`                | `http://localhost:3000` → HTTP 200         |
| Temporal UI      | `temporal-ui`             | `http://localhost:8080` → HTTP 200         |
| Temporal server  | `temporal`                | conteneur `healthy`, port 7234             |
| Temporal DB      | `temporal-db`             | conteneur `healthy`                        |
| Temporal worker  | `temporal-worker`         | conteneur `Up` (pas de redémarrage en boucle) |
| Supabase API     | CLI (`supabase status`)   | `http://localhost:54321/rest/v1/` → HTTP 200 |
| Supabase Studio  | CLI                       | `http://localhost:54323` accessible        |

## Procédure (à suivre dans l'ordre)

### Phase 1 — Démarrage (modèle Haiku)

Délègue à un sous-agent avec l'outil `task` :
- `agent_type: "task"`
- `model: "claude-haiku-4.5"`

Instructions à donner au sous-agent (contexte complet, il est sans état) :
1. Vérifier que Docker répond (`docker info`). S'il ne répond pas, signale-le
   clairement et arrête-toi (l'utilisateur doit lancer Docker Desktop).
2. Si `.env` est absent à la racine du projet, le créer :
   `Copy-Item .env.example .env`.
3. Lancer le démarrage : `make up` (prévoir un délai long, le premier run
   télécharge des images Docker — initial_wait ≥ 240 s).
4. Rapporter : le code de sortie, et la présence (ou non) de la ligne finale
   « Stack up. Frontend ... ».

### Phase 2 — Contrôle de santé (modèle Haiku)

Délègue à un sous-agent avec l'outil `task` :
- `agent_type: "task"`
- `model: "claude-haiku-4.5"`

Instructions à donner au sous-agent :
1. Lister l'état des conteneurs :
   `docker compose ps --format "table {{.Name}}\t{{.Status}}\t{{.Ports}}"`.
2. Vérifier Supabase : `supabase status`.
3. Tester les endpoints HTTP (doivent renvoyer 200) :
   `http://localhost:3000`, `http://localhost:8080`,
   `http://localhost:54321/rest/v1/`.
4. Rapporter une **liste précise et structurée** : pour chaque service du tableau
   ci-dessus → `OK` ou `KO` avec le symptôme exact (conteneur absent, `Restarting`,
   `Exited`, `unhealthy`, code HTTP ≠ 200, timeout, etc.).

Tu (orchestrateur) interprètes le rapport :
- **Tous les services OK** → va à « Fin ».
- **Au moins un service KO** → va à la Phase 3.

### Phase 3 — Diagnostic et réparation (modèle Opus)

Délègue à un sous-agent avec l'outil `task` :
- `agent_type: "general-purpose"`
- `model: "claude-opus-4.8"`

Transmets-lui la **liste exacte des composants KO** issue de la Phase 2, le
tableau des services attendus, et ces instructions :
1. **Chercher** la cause racine : inspecter les logs du/des composant(s) en échec
   (`docker compose logs --tail 200 <service>`, `make logs-temporal`,
   `make logs-frontend`, `supabase status`, `docker ps -a`), vérifier les ports
   occupés, l'état de `.env`, les images, les volumes.
2. **Analyser** : identifier la cause précise (port déjà utilisé, variable
   d'environnement manquante/incorrecte, image corrompue, migration Supabase en
   échec, dépendance non installée, conteneur qui crash au démarrage, etc.).
3. **Réparer** de façon ciblée et la moins destructive possible : corriger la
   config, libérer un port, recréer un conteneur (`docker compose up -d --force-recreate <service>`),
   relancer Supabase, et en dernier recours `make reset` (⚠️ détruit les volumes
   et réapplique migrations + seed) — uniquement si nécessaire et après l'avoir
   justifié.
4. Re-vérifier que les composants ciblés sont revenus à l'état sain et rapporter
   ce qui a été corrigé.

Ne modifie pas le code applicatif ni les migrations livrées pour « réparer » la
stack, sauf si le diagnostic prouve qu'un fichier est réellement en cause ; dans
ce cas, fais la correction minimale et explique-la.

### Boucle

Après la Phase 3, **relance la Phase 2** (contrôle de santé Haiku). Répète le
cycle Phase 2 → Phase 3 jusqu'à ce que tous les services soient OK. Limite à
**5 itérations** : si la stack n'est toujours pas saine après 5 cycles, arrête-toi
et présente à l'utilisateur un résumé des échecs persistants et des hypothèses
restantes.

## Fin

Le skill se termine **uniquement** quand le contrôle de santé confirme que tous
les services attendus sont OK. Fournis alors un récapitulatif final :
- la liste des services avec leur URL,
- les réparations éventuellement appliquées,
- les commandes utiles : `make logs`, `make down`, `make reset`.

## Règles

- Toujours respecter le modèle imposé par phase : **Haiku** pour démarrage et
  santé, **Opus** pour diagnostic/réparation.
- Donne à chaque sous-agent un contexte complet (il est sans état).
- Ne déclare jamais la stack « prête » sans une vérification de santé qui passe.
