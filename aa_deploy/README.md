# Despliegue Debian

Guia minima para ejecutar la instancia `release` del bot en Debian usando `systemd`.

## Estructura asumida

Este ejemplo asume esta ruta de despliegue:

```text
/opt/bigness-league
```

Dentro de esa carpeta debe vivir el proyecto completo, incluyendo:

- `src/`
- `aa_resources/`
- `aa_var/`
- `.env`

## Dependencias base

```bash
sudo apt update
sudo apt install -y git python3 python3-venv
```

## Copiar el proyecto

```bash
sudo mkdir -p /opt/bigness-league
sudo chown -R "$USER":"$USER" /opt/bigness-league
git clone <URL_DEL_REPO> /opt/bigness-league
cd /opt/bigness-league
git checkout master
```

## Entorno virtual e instalacion

```bash
cd /opt/bigness-league
python3 -m venv .venv
. .venv/bin/activate
pip install --upgrade pip
pip install -e .
```

## Configuracion

Coloca tu archivo `.env` de produccion en:

```text
/opt/bigness-league/.env
```

Valores recomendados de base para produccion:

```env
BOT_ENV=production
BOT_SYNC_SCOPE=global
BOT_LOG_DIR=aa_var/logs
```

## Servicio systemd

1. Revisa y ajusta `Despliegue/bigness-league.service` si cambias:
    - usuario
    - grupo
    - ruta de despliegue
2. Copialo a `systemd`:

```bash
sudo cp /opt/bigness-league/Despliegue/bigness-league.service /etc/systemd/system/bigness-league.service
sudo systemctl daemon-reload
sudo systemctl enable --now bigness-league
```

## Comandos utiles

Ver estado del servicio:

```bash
sudo systemctl status bigness-league
```

Reiniciar despues de actualizar codigo o `.env`:

```bash
sudo systemctl restart bigness-league
```

Seguir logs del servicio en tiempo real:

```bash
journalctl -u bigness-league -f
```

Ver ultimas lineas del servicio:

```bash
journalctl -u bigness-league -n 200
```

Seguir el archivo de log rotativo del bot:

```bash
tail -F /opt/bigness-league/aa_var/logs/bigness_league.log
```

Filtrar errores y warnings:

```bash
tail -F /opt/bigness-league/aa_var/logs/bigness_league.log | grep -E "ERROR|WARNING"
```

Buscar fallos de slash commands:

```bash
journalctl -u bigness-league -f | grep SLASH_COMMAND_ERROR
```

## Actualizacion tipica

```bash
cd /opt/bigness-league
git pull
. .venv/bin/activate
pip install -e .
sudo systemctl restart bigness-league
```

## Notas

- No comprimas el proyecto en un unico `.py`.
- Manten el despliegue con la estructura completa del repo.
- `tail -F` es preferible a `tail -f` porque el logger rota `bigness_league.log`.
- El bot carga `.env` desde el directorio de trabajo, por eso el `WorkingDirectory` del servicio debe apuntar a la raiz
  del proyecto.
