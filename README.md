# Jarvis — Asistente de IA personal (TFG)

Proyecto de Fin de Grado: un asistente de IA personal con voz, estilo Jarvis,
construido sobre [OpenJarvis](https://github.com/open-jarvis/OpenJarvis)
(Apache 2.0). Usa **Google Gemini** como motor de IA (texto, voz nativa de
entrada/salida) y se conecta a Gmail y Google Calendar para gestionar correo
y reuniones (con Google Meet) por voz o por chat.

## Qué incluye

- **Chat de texto y llamada de voz manos libres**: pulsa el núcleo azul para
  iniciar una llamada continua con detección real de silencios (no hay que
  pulsar nada entre turnos), con una interfaz de pantalla completa en negro
  mientras estás en la llamada.
- **Palabra de activación** ("Jarvis") opcional, detectada en el navegador
  sin coste de API.
- **Voz nativa de Gemini** tanto para entender audio (STT) como para hablar
  (TTS) — no se usan servicios de voz de terceros.
- **Gmail**: buscar correos, leer hilos, listar no leídos, enviar correos.
- **Google Calendar**: ver eventos de hoy, buscar eventos, próxima reunión,
  crear eventos con enlace de Google Meet.

## Requisitos previos

- [Python 3.10–3.13](https://www.python.org/) y [uv](https://docs.astral.sh/uv/)
  (gestor de paquetes de Python: `pip install uv` o `winget install astral-sh.uv`).
- [Node.js 18+](https://nodejs.org/) para el frontend.
- Una **clave de API de Gemini** gratuita en
  [Google AI Studio](https://aistudio.google.com/apikey).
- (Opcional) Credenciales OAuth de Google Cloud si quieres usar Gmail/Calendar
  — ver más abajo.

## Instalación

```bash
git clone https://github.com/TenMM2/jarvis-ai.git
cd jarvis-ai

# Backend (instala OpenJarvis en modo editable)
uv pip install -e .

# Frontend
cd frontend
npm install
cd ..
```

## Configuración

1. Copia `.env.example` a `.env` y pega tu clave de Gemini:

   ```bash
   cp .env.example .env
   ```

   ```
   GEMINI_API_KEY=tu_clave_aqui
   ```

   El archivo `.env` nunca se sube al repositorio (ver `.gitignore`).

2. (Primera vez) revisa que `~/.openjarvis/config.toml` tenga Gemini como
   motor por defecto. Si no existe, `jarvis` lo crea con valores por defecto
   la primera vez que arrancas.

## Arranque

```bash
jarvis gui
```

Esto levanta el backend (`http://127.0.0.1:8000`) y el frontend
(`http://127.0.0.1:5173`) y abre el navegador automáticamente. Al abrir, la
app detecta la clave de Gemini del servidor y selecciona el modelo en la nube
sin pasos adicionales.

## Conectar Gmail y Calendar (opcional)

1. Crea un proyecto en [Google Cloud Console](https://console.cloud.google.com/),
   habilita las APIs de Gmail y Calendar, y crea credenciales OAuth de tipo
   "App de escritorio".
2. Ejecuta:

   ```bash
   jarvis connect gmail
   ```

   Pega el Client ID y Client Secret cuando se te pidan; se abrirá el
   navegador para autorizar el acceso. La misma autorización cubre también
   Calendar.

## Licencia y procedencia

Este proyecto parte de [OpenJarvis](https://github.com/open-jarvis/OpenJarvis),
publicado bajo licencia **Apache 2.0** (ver [LICENSE](LICENSE)). Se mantiene
dicha licencia; las modificaciones de este repositorio (integración de
Gemini, voz nativa, herramientas de Gmail/Calendar, interfaz de llamada,
etc.) son obra propia para este Proyecto de Fin de Grado.
