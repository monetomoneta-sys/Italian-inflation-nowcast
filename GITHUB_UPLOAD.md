# Pubblicazione su GitHub

## Metodo consigliato: GitHub CLI

### 1. Installa gli strumenti

- Git: https://git-scm.com/downloads
- GitHub CLI: https://cli.github.com/

### 2. Apri il terminale nella cartella del progetto

Windows: apri la cartella, clicca sulla barra dell'indirizzo, scrivi `powershell` e premi Invio.

macOS: nel Terminale esegui `cd` seguito dal percorso della cartella.

### 3. Configura il tuo nome Git, solo la prima volta

```bash
git config --global user.name "Nome Cognome"
git config --global user.email "email-associata-a-github@example.com"
```

### 4. Autenticati

```bash
gh auth login
```

Seleziona:

1. `GitHub.com`
2. `HTTPS`
3. autenticazione tramite browser

### 5. Controlla ciò che verrà pubblicato

```bash
git status
```

Assicurati che non compaiano `data/`, `.venv/`, `reports/`, `.env` o profili browser.

### 6. Inizializza e crea il primo commit

```bash
git init
git add .
git status
git commit -m "Initial Esselunga inflation nowcast prototype"
```

### 7. Crea il repository e pubblicalo

```bash
gh repo create italian-online-inflation-nowcast --public --source=. --remote=origin --push
```

Per un repository privato sostituisci `--public` con `--private`.

### 8. Aggiornamenti futuri

```bash
git add .
git commit -m "Describe the change"
git push
```

## Metodo alternativo: sito GitHub + Git

1. Su GitHub seleziona `New repository`.
2. Nome: `italian-online-inflation-nowcast`.
3. Non aggiungere README, `.gitignore` o licenza dal sito, perché esistono già localmente.
4. Crea il repository.
5. Copia l'URL HTTPS mostrato da GitHub.
6. Nel terminale esegui:

```bash
git init
git add .
git commit -m "Initial Esselunga inflation nowcast prototype"
git branch -M main
git remote add origin https://github.com/TUO-USERNAME/italian-online-inflation-nowcast.git
git push -u origin main
```

GitHub non accetta la password dell'account come password Git. Usa GitHub CLI, Git Credential Manager, SSH oppure un personal access token.
