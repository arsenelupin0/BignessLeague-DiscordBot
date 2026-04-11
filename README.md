# Bigness League Bot

Base inicial de un bot de Discord usando `discord.py`, con soporte para slash commands.

## Requisitos

- Python 3.11 o superior
- Un bot creado en el [Discord Developer Portal](https://discord.com/developers/applications)

## Instalacion

```powershell
python -m venv .venv
.\.venv\Scripts\activate
pip install -e .
```

## Configuracion

1. Crea tu archivo `.env` a partir de `.env.example`.
2. Define `DISCORD_TOKEN` con el token del bot.
3. Define `DISCORD_GUILD_ID` con el ID de tu servidor de pruebas.
4. Opcionalmente ajusta `BOT_PREFIX` si quieres usar otro prefijo para comandos de texto.
5. Ajusta `BOT_ENV` y `BOT_SYNC_SCOPE` segun el entorno.
6. Ajusta las variables `BOT_LOG_*` si quieres mas o menos verbosidad.

Si defines `DISCORD_GUILD_ID`, los slash commands se sincronizan en ese servidor y aparecen casi al instante. Si lo
dejas vacio, se sincronizan globalmente y Discord puede tardar en propagarlos.

Para usar el comando de texto `!sync`, activa tambien `Message Content Intent` en el Developer Portal, dentro de la
seccion `Bot`.

La sincronizacion ahora sigue una politica fija por proceso:

- `BOT_ENV=development` suele ir con `BOT_SYNC_SCOPE=guild`
- `BOT_ENV=production` suele ir con `BOT_SYNC_SCOPE=global`

El comando `!sync` solo permite el scope configurado en ese arranque. Si quieres cambiar entre `guild` y `global`,
cambia el `.env` y reinicia el bot. Asi evitas mezclar scopes por accidente.

## Ejecucion

```powershell
bigness-bot
```

Alternativamente:

```powershell
python -m bigness_league_bot.main
```

## Slash command incluido

- `/countchars text:<texto>`: devuelve cuantos caracteres tiene la cadena enviada.
- `/cerrar_canal accion:<opcion>`: aplica acciones de cierre sobre el canal actual.

Opciones disponibles en `/cerrar_canal`:

- `Partido jugado`: deja el canal en modo solo lectura para el resto de roles y mantiene escritura para `Staff`,
  `Administrador` y `Ceo`.
- `Jornada cerrada`: oculta el canal para los roles no protegidos y deja acceso solo a `Staff`, `Administrador` y `Ceo`.
- `Reabrir partido`: restaura lectura y escritura para todos los miembros del canal.
- `Eliminacion de canal`: pide confirmacion con botones y elimina el canal por completo.

Restricciones de `/cerrar_canal`:

- solo funciona en canales cuyo nombre cumpla `j[1-9][0-9]?-partido-[1-9][0-9]?`
- solo pueden usarlo miembros con alguno de estos roles: `Staff`, `Administrador`, `Ceo`
- las respuestas del comando son publicas

## Comandos de desarrollo

- `!sync guild`: fuerza la sincronizacion de slash commands en la guild configurada.
- `!sync global`: fuerza la sincronizacion global.
- `!slashstatus`: muestra que comandos slash tiene cargados el bot localmente.

Los comandos de desarrollo usan el prefijo definido en `BOT_PREFIX` y estan limitados al propietario de la aplicacion.
`!sync` solo acepta el scope configurado en `BOT_SYNC_SCOPE`.

## Estructura recomendada

```text
src/bigness_league_bot/
  app/               # arranque y bootstrap
  core/              # configuracion y primitivas compartidas
  application/       # casos de uso y servicios puros
  infrastructure/    # integraciones externas, como Discord
  presentation/      # cogs, comandos y adaptadores de entrada
```

La idea es que la logica reusable viva en `application/` y que `presentation/discord` solo traduzca interacciones de
Discord hacia esos casos de uso.

## Logs

El bot escribe logs en consola y en `logs/bigness_league.log`.

Se registran:

- conexion y reconexion del bot
- entrada y salida de servidores
- slash commands recibidos y completados
- comandos de texto recibidos y completados
- errores de slash commands y comandos de texto
- todos los mensajes, si activas `BOT_LOG_ALL_MESSAGES=true`

## Diagnostico rapido si `/` no muestra comandos

1. Reinicia el bot y revisa la consola.
2. Debes ver una linea como `Sincronizacion completada: scope=guild:... total=...`.
3. Si no aparece, el bot no esta llegando a sincronizar.
4. Si aparece pero Discord no muestra nada, reinvita la aplicacion asegurando el scope `applications.commands`.
5. Si quieres forzarlo manualmente, usa `!sync guild`.
