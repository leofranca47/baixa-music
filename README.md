# Baixa YouTube 🎵

Aplicação web local minimalista (FastAPI + HTML5/Tailwind CSS) para baixar e extrair áudio de vídeos do YouTube em formatos de alta qualidade (`MP3`, `M4A` e `WAV`) utilizando diretamente `yt-dlp` e `ffmpeg` em subprocesso no servidor.

## 🚀 Funcionalidades

- **Extração de Áudio Local:** Executa `yt-dlp` com flags de alta fidelidade (`--extract-audio --audio-quality 0`) e conversão via `ffmpeg`.
- **Formatos Suportados:** `MP3` (padrão), `M4A` e `WAV`.
- **Interface Intuitiva:** Página única limpa com Tailwind CSS, feedback visual de processamento (spinner/status) e download automático imediato.
- **Ciclo de Vida Limpo:** Os arquivos temporários são armazenados em diretórios temporários isolados e excluídos automaticamente após o término do streaming de download pelo navegador.
- **Segurança:** Execução de subprocessos com lista explícita de argumentos (`asyncio.create_subprocess_exec`) sem shell (`shell=False`), prevenindo injeção de comandos.
- **Autenticação Opcional via Cookies:** Se existir um arquivo de cookies do YouTube (Netscape format), ele é repassado ao yt-dlp com `--cookies`, contornando bot-check/403 em IPs de datacenter.

---

## 📋 Pré-requisitos

Certifique-se de ter instalado no sistema operacional:
- **Python 3.10+**
- **yt-dlp** (ex: `sudo pacman -S yt-dlp` ou `sudo apt install yt-dlp` ou via pip)
- **ffmpeg** (ex: `sudo pacman -S ffmpeg` ou `sudo apt install ffmpeg`)
- **Node.js 20+** (runtime JS exigido pelo yt-dlp para os desafios do YouTube; habilitado via `--js-runtimes node`)
- **Docker** (para o servidor de PO token — ver abaixo)

### Servidor de PO Token (bgutil) — obrigatório em produção

O YouTube aplica bot-check a IPs de datacenter. O provider bgutil gera PO tokens
que tornam o tráfego anônimo mais legítimo:

```bash
docker run -d --init --name bgutil-provider --restart unless-stopped \
  -p 127.0.0.1:4416:4416 brainicism/bgutil-ytdlp-pot-provider
```

O plugin (`pip install bgutil-ytdlp-pot-provider`, já no requirements.txt) conecta
automaticamente em 127.0.0.1:4416 e o app força a negociação com
`youtube:fetch_pot=always`. Sem o container no ar o site ainda funciona, mas vídeos
protegidos por bot-check falham.

### Cookies do YouTube (necessário para vídeos com bot-check)

Mesmo com PO token, o YouTube pode exigir sessão logada para vídeos específicos
a partir de IPs de datacenter. Exporte os cookies de uma sessão logada:

Exporte os cookies de uma sessão logada com uma extensão como "Get cookies.txt LOCALLY"
e salve como `cookies.txt` na raiz do projeto (ou aponte `YTDLP_COOKIES_FILE` para outro
caminho). O arquivo é lido a cada conversão — atualizar o conteúdo não exige restart.
Cookies expirados/rotacionados geram apenas um warning e o download segue anônimo.

---

## 🛠️ Instalação e Execução

### 1. Criar e ativar o ambiente virtual

```bash
python3 -m venv .venv
source .venv/bin/activate
```

### 2. Instalar dependências

```bash
pip install -r requirements.txt
```

### 3. Iniciar o servidor de desenvolvimento

```bash
uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```

Abra no seu navegador: [http://127.0.0.1:8000](http://127.0.0.1:8000)

---

## 🧪 Executando os Testes

Os testes automatizados cobrem rotas HTTP, validação de entradas, execução de subprocesso e limpeza de arquivos temporários:

```bash
pytest
```

---

## 📡 API Endpoints

- `GET /`: Serve a interface web interativa.
- `POST /api/convert`: Inicia a extração e conversão do áudio.
  - Payload JSON:
    ```json
    {
      "url": "https://www.youtube.com/watch?v=...",
      "format": "mp3"
    }
    ```
- `GET /api/download/{task_id}`: Faz o streaming do arquivo final para download no navegador e agenda a exclusão do arquivo temporário.
# baixa-music
