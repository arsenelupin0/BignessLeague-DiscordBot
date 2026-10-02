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
- `.env.production`
- `.env` privado del servidor, ignorado por Git

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

Coloca `.env.production` y el `.env` privado en la raíz del proyecto indicada por `WorkingDirectory` en
`aa_deploy/bigness-league.service`. La plantilla actual usa:

```text
/home/bigness/DiscordBot/BignessLeague-DiscordBot/.env.production
```

Valores recomendados de base para produccion:

```env
BOT_ENV=production
BOT_SYNC_SCOPE=global
BOT_LOG_DIR=aa_var/logs
```

`.env.production` está versionado y es la plantilla completa de producción: contiene los ajustes oficiales (hojas,
canales, roles, tiempos, etc.) y las claves de credenciales con valores vacíos.
Las credenciales se guardan en el `.env` privado de esa instalación, que Git ignora. Basta con guardar los tokens
y cualquier ajuste que quieras sobrescribir; el resto se obtiene de `.env.production`. No necesitas otra plantilla
ni copiar el perfil entero. No pongas tokens reales en los archivos versionados.
Las sustituciones se aplican por nombre de clave al cargar la configuración; no modifican `.env.production`.

Si utilizas `/opt/bigness-league`, ajusta también `WorkingDirectory`, `PYTHONPATH` y `ExecStart` del servicio a esa
ruta. Systemd establece `BOT_ENV=production`; el cargador Python lee `.env.production` y después aplica `.env`.
Así los ajustes locales prevalecen sobre el perfil y los tokens permanecen fuera de Git. El servicio no utiliza
`EnvironmentFile`: ambos entornos comparten la misma lógica de carga en Python.

## Servicio systemd

1. Revisa y ajusta `aa_deploy/bigness-league.service` si cambias:
    - usuario
    - grupo
    - ruta de despliegue
2. Copialo a `systemd`:

```bash
sudo cp /opt/bigness-league/aa_deploy/bigness-league.service /etc/systemd/system/bigness-league.service
sudo systemctl daemon-reload
sudo systemctl enable --now bigness-league
```

## Comandos utiles

Ver estado del servicio:

```bash
sudo systemctl status bigness-league
```

Reiniciar despues de actualizar codigo, `.env.production` o las credenciales de `.env`:

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
- El bot busca `.env` y el perfil seleccionado en la raíz del proyecto, calculada desde el paquete Python.
  Mantén `WorkingDirectory` apuntando a esa raíz para el resto de rutas relativas del despliegue.
