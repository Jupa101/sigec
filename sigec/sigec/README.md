# SIGEC - Sistema de Gestión y Seguimiento de Capacitaciones
Aplicación web (Flask + SQLite) con usuarios y roles, capacitaciones, participantes, inscripciones con control de cupos, asistencia y reportes (con CSV).

## Ejecutar local
    pip install -r requirements.txt && python app.py      # http://localhost:8000
Acceso inicial: `admin` / `admin123` (cámbialo con las variables de abajo antes de publicar).

## Variables de entorno
SECRET_KEY (obligatoria en producción), ADMIN_USER y ADMIN_PASS (solo se usan al crear la BD), DB_PATH (ruta de SQLite), PORT.

## Desplegar
**Docker (cualquier servidor):** `docker build -t sigec . && docker run -d -p 80:8000 -v sigec-data:/data -e SECRET_KEY=$(openssl rand -hex 32) -e ADMIN_PASS=ClaveSegura123 sigec`
**Render / Railway:** crea un Web Service desde el repositorio (Docker), define SECRET_KEY y ADMIN_PASS, y agrega un disco persistente montado en `/data` (sin disco, SQLite se borra en cada despliegue).

## Despliegue con Docker Compose (recomendado)
    cp .env.example .env     # edita SECRET_KEY y ADMIN_PASS
    docker compose up -d --build
La app queda en http://IP_DEL_SERVIDOR (puerto 80). Los datos viven en el volumen `sigec-data`.
Ver registros: `docker compose logs -f` · Actualizar: `git pull && docker compose up -d --build` · Respaldar la BD: `docker compose cp sigec:/data/sigec.db ./respaldo.db`

## Render (plan gratuito)
Sube la carpeta a GitHub, en Render elige New > Blueprint (usa `render.yaml`) o New > Web Service > Docker. Define `ADMIN_PASS`.
Con `SEED_DEMO=1` la app crea datos de ejemplo cuando la base está vacía. En el plan gratuito el disco no es persistente: los datos reales pueden perderse al reiniciar o redesplegar.
