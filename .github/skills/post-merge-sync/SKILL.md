---
name: post-merge-sync
description: >-
  Guide la mise à jour sûre du dépôt local après qu'une pull request a été
  validée et mergée par un humain, puis nettoie la branche locale et la branche
  distante restée ouverte quand c'est sans risque.
user-invocable: true
---

# Synchronisation post-merge

Tu aides l'utilisateur après ce scénario :

- une pull request a été relue, validée, puis mergée par un humain ;
- la branche distante de la PR existe encore ;
- le dépôt local est encore sur l'ancienne branche ou n'est pas à jour.

Ton objectif est de proposer et appliquer les bonnes pratiques de mise à jour du
dépôt local, sans perdre de travail local.

## Entrée

L'utilisateur peut fournir :

- un numéro de PR, par exemple `#2` ou `2` ;
- une URL de PR GitHub ;
- un nom de branche, par exemple `spec-1-odt-file-support`.

Si aucune entrée n'est fournie, tente d'inférer la branche courante avec :

```powershell
git branch --show-current
```

Si tu ne peux pas identifier la PR ou la branche concernée avec confiance, pose
une seule question de clarification.

## Règles de sécurité

- Ne jamais supprimer une branche distante sans avoir vérifié que la PR
  correspondante est bien `MERGED`.
- Ne jamais supprimer `main`, `master`, la branche par défaut, ni une branche
  protégée.
- Ne jamais utiliser `git reset --hard`, `git checkout --`, `git clean`, ou
  `git branch -D` sans demande explicite de l'utilisateur.
- Si `git status --short` montre des changements locaux, arrêter et demander à
  l'utilisateur s'il veut commit, stash, ou abandonner ces changements. Ne rien
  écraser.
- Utiliser `git pull --ff-only` pour éviter les merges locaux accidentels.
- Préférer `git branch -d` à `git branch -D`; si `-d` refuse, investiguer au
  lieu de forcer.

## Bonnes pratiques à appliquer

### 1. Identifier le contexte

```powershell
gh auth status
gh repo view --json nameWithOwner,defaultBranchRef --jq '{repo:.nameWithOwner, default:.defaultBranchRef.name}'
git branch --show-current
git --no-pager status --short
git fetch --prune origin
```

Déduis :

- la branche par défaut (`main` dans ce dépôt, sauf indication GitHub contraire) ;
- la branche locale courante ;
- la branche distante de la PR ;
- le numéro et l'état de la PR.

Pour une PR connue :

```powershell
gh pr view <pr-number-or-url> --json number,state,mergedAt,headRefName,baseRefName,url,title
```

Pour une branche connue :

```powershell
gh pr list --state all --head <branch> --json number,state,mergedAt,headRefName,baseRefName,url,title --limit 10
```

Si plusieurs PRs correspondent à la branche, demande laquelle utiliser.

### 2. Vérifier que la PR est vraiment mergée

Continuer uniquement si :

- `state` vaut `MERGED` ou `mergedAt` est renseigné ;
- `baseRefName` correspond à la branche par défaut attendue ;
- `headRefName` correspond à la branche à nettoyer.

Si la PR est encore `OPEN`, ne supprime rien. Explique que le bon réflexe est
d'attendre le merge ou de fermer explicitement la PR.

### 3. Protéger le travail local

Avant toute modification locale :

```powershell
git --no-pager status --short
```

Si la sortie n'est pas vide, arrêter. Proposer ces options :

1. commit des changements locaux ;
2. `git stash push -m "pre-post-merge-sync"` ;
3. abandon manuel par l'utilisateur.

Ne choisis pas à la place de l'utilisateur.

### 4. Revenir sur la branche par défaut

Si la branche courante est la branche de PR :

```powershell
git switch <default-branch>
```

Sinon, ne change de branche que si c'est nécessaire pour mettre à jour le dépôt
ou supprimer la branche locale.

### 5. Mettre à jour le dépôt local proprement

```powershell
git fetch --prune origin
git pull --ff-only origin <default-branch>
```

Si `git pull --ff-only` échoue, ne fais pas de merge automatique. Explique le
blocage et demande une décision.

### 6. Supprimer la branche locale mergée

Vérifier d'abord que Git la considère mergée :

```powershell
git branch --merged <default-branch>
```

Puis supprimer localement :

```powershell
git branch -d <merged-branch>
```

Si `git branch -d` refuse, ne force pas. Vérifie les commits restants avec :

```powershell
git --no-pager log --oneline <default-branch>..<merged-branch>
```

Puis demande confirmation avant toute action destructive.

### 7. Supprimer la branche distante restée ouverte

Après confirmation que la PR est mergée et que la branche n'est pas protégée :

```powershell
git push origin --delete <merged-branch>
```

Si GitHub indique que la branche distante n'existe déjà plus, considère cela
comme un état final acceptable.

### 8. Nettoyer les références distantes et vérifier

```powershell
git fetch --prune origin
git --no-pager status --short
git branch -vv
gh pr view <pr-number-or-url> --json number,state,mergedAt,headRefName,url
```

La fin attendue :

- dépôt local sur la branche par défaut ;
- branche par défaut à jour avec `origin/<default-branch>` ;
- branche locale de PR supprimée ;
- branche distante de PR supprimée ou déjà absente ;
- aucun changement local non traité.

## Cas particuliers

### La branche locale contient des commits non poussés

Ne supprime pas la branche. Vérifie :

```powershell
git --no-pager log --oneline origin/<branch>..<branch>
```

Explique que ces commits ne sont pas sur la branche distante et demande si
l'utilisateur veut les conserver, les cherry-pick, ou les abandonner.

### La PR a été squash-merged

`git branch -d <branch>` peut parfois refuser si les commits de la branche ne
sont pas identiques à l'historique de `main`. Dans ce cas :

1. vérifier sur GitHub que la PR est bien mergée ;
2. vérifier qu'aucun commit local non poussé n'existe ;
3. demander confirmation avant d'utiliser une suppression locale forcée.

Ne force jamais automatiquement.

### La branche distante est déjà supprimée

Ne traite pas cela comme une erreur. Lance seulement :

```powershell
git fetch --prune origin
```

Puis supprime la branche locale si elle est mergée ou si l'utilisateur confirme
qu'elle peut être supprimée.

## Réponse finale

Réponds en français avec :

- la PR et la branche traitées ;
- la branche locale courante finale ;
- si la branche locale a été supprimée ;
- si la branche distante a été supprimée ou était déjà absente ;
- les commandes importantes exécutées ;
- tout point bloquant ou action manuelle restante.
