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
6. Ajusta `BOT_DEFAULT_LOCALE` y `BOT_LOCALES_DIR` si quieres cambiar el idioma base o la carpeta de catalogos.
7. Ajusta las variables `BOT_LOG_*` si quieres mas o menos verbosidad.
8. Ajusta `BOT_TIMEZONE` si quieres interpretar las fechas y horas de los partidos en otra zona horaria.
   Puedes usar `local`, un offset como `+02:00`, o una zona IANA valida si tu entorno dispone de datos de zona horaria.
9. Si quieres cambiar los botones del mensaje inicial de los partidos, ajusta `BOT_MATCH_CHANNEL_TICKET_URL` y
   `BOT_MATCH_CHANNEL_RULES_URL`.
10. Si quieres usar `/ver_mi_equipo`, configura `BOT_GOOGLE_SERVICE_ACCOUNT_FILE`
    y `BOT_GOOGLE_SHEETS_SPREADSHEET_ID`. `BOT_GOOGLE_SHEETS_TEAM_SHEET_NAME` es opcional.

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

- `/cerrar_canal accion:<opcion>`: aplica acciones de cierre sobre el canal actual.
- `/anadir_al_canal`: abre un selector filtrado para anadir roles al canal actual.
-
`/canal_de_jornada jornada:<numero> partido:<numero> minutos_cortesia:<numero> fecha:<texto> hora:<texto> bo_x:<numero> categoria:<division> equipo_1:<rol> equipo_2:<rol>`:
crea un canal de partido con permisos para ambos equipos.

- `/ver_mi_equipo`: busca tu equipo en Google Sheets a partir de tu rol de Discord y muestra su ficha.

Opciones disponibles en `/cerrar_canal`:

- `Partido jugado`: deja el canal en modo solo lectura para el resto de roles y mantiene escritura para `Staff`,
  `Administrador` y `Ceo`. Tambien cambia el icono final del canal a `✅`.
- `Jornada cerrada`: oculta el canal para los roles no protegidos, deja acceso solo a `Staff`, `Administrador` y `Ceo`
  y cambia el icono final del canal a `🔒`.
- `Reabrir partido`: restaura la escritura para los roles que ya tenian acceso al canal y devuelve el icono final a `⚽`.
- `Eliminacion de canal`: pide confirmacion con botones y elimina el canal por completo.

Restricciones de `/cerrar_canal`:

- solo funciona en canales cuyo nombre cumpla `j[1-9][0-9]?-partido-[1-9][0-9]?`
- solo pueden usarlo miembros con alguno de estos roles: `Staff`, `Administrador`, `Ceo`
- las respuestas del comando son publicas

`/anadir_al_canal`:

- solo funciona en canales cuyo nombre cumpla `j[1-9][0-9]?-partido-[1-9][0-9]?`
- solo pueden usarlo miembros con alguno de estos roles: `Staff`, `Administrador`, `Ceo`
- muestra solo roles entre los separadores configurados en `BOT_CHANNEL_ACCESS_RANGE_START_ROLE_ID` y
  `BOT_CHANNEL_ACCESS_RANGE_END_ROLE_ID`
- incluye busqueda propia por nombre parcial, ID o mencion de rol

`/canal_de_jornada`:

- solo puede usarlo un miembro con `Staff`, `Administrador` o `Ceo`
- crea el canal con nombre `『𝗝』1️⃣『𝗣』2️⃣・⚽`
- oculta el canal para `@everyone`
- permite elegir la categoria de destino entre `Gold Division` y `Silver Division`
- recibe minutos de cortesia, fecha, hora y formato `BoX`
- da acceso de lectura y escritura a `Staff`, `Administrador`, `Ceo`, `equipo_1` y `equipo_2`
- interpreta `fecha` como `DD/MM/YYYY` o `YYYY-MM-DD`, y `hora` como `HH:MM`
- usa `BOT_TIMEZONE` para convertir fecha y hora al timestamp de Discord
- valida que los dos roles de equipo sean distintos y esten dentro del rango de roles configurado
- usa `BOT_GOLD_DIVISION_CATEGORY_ID` y `BOT_SILVER_DIVISION_CATEGORY_ID` para resolver las categorias reales
- envia automaticamente un mensaje inicial con menciones a ambos equipos, tres embeds informativos y botones URL para
  ticket y normativa

`/ver_mi_equipo`:

- exige que tengas exactamente un rol de equipo dentro del rango configurado
- `Staff`, `Administrador` y `Ceo` pasan la validacion general del comando, pero el bot sigue necesitando identificar un
  unico rol de equipo para saber que bloque mostrar
- busca el bloque de tu equipo en la hoja de Google Sheets configurada
- toma la division directamente del nombre de la hoja
- lee el tracker desde el hipervinculo de la celda `Jugador`
- devuelve la ficha del equipo como tablas ANSI en varios mensajes si hace falta

Configuracion de Google Sheets:

- `BOT_GOOGLE_SERVICE_ACCOUNT_FILE`: ruta al JSON de la cuenta de servicio con acceso de lectura a la hoja
- `BOT_GOOGLE_SHEETS_SPREADSHEET_ID`: ID del documento de Google Sheets
- `BOT_GOOGLE_SHEETS_TEAM_SHEET_NAME`: opcional. Si lo dejas vacio, el bot buscara en todas las sheets del documento.
  Tambien admite varios nombres separados por comas si quieres limitar la busqueda.
- la hoja debe estar organizada por bloques de equipo con este esquema: titulo del equipo, cabecera `Jugador`,
  `Discord`, `Epic Name`, `Rocket In-Game Name`, `MMR`, hasta 6 jugadores y una fila de resumen con fichajes restantes
  y media del equipo

## Localizacion

El bot carga sus textos desde `aa_resources/locales/`.

- `aa_resources/locales/es-ES.json`: catalogo base en espanol
- `aa_resources/locales/en-US.json`: ejemplo de segundo idioma
- `BOT_DEFAULT_LOCALE`: locale de fallback del bot
- `BOT_LOCALES_DIR`: directorio donde se cargan los catalogos

La localizacion cubre:

- nombres y descripciones de slash commands
- opciones visibles de comandos y componentes
- mensajes de respuesta, validacion y error

Para anadir un idioma nuevo, crea otro JSON con el nombre del locale de Discord, por ejemplo `fr.json` o `fr-FR.json`,
y replica las mismas claves.

Las claves no se referencian ya como cadenas crudas en el codigo. El flujo recomendado es:

1. Edita `aa_resources/locales/es-ES.json`.
2. Regenera el modulo tipado:

```powershell
python aa_scripts\i18n\generate_i18n_keys.py --catalog aa_resources\locales\es-ES.json --output src\bigness_league_bot\infrastructure\i18n\keys.py
```

3. Usa las claves desde `I18N`, por ejemplo `I18N.actions.channel_management.add_roles_summary`.

Esto te da autocompletado en IntelliJ IDEA y evita typos en las rutas de traduccion.

## Comandos de desarrollo

- `!sync guild`: fuerza la sincronizacion de slash commands en la guild configurada.
- `!sync global`: fuerza la sincronizacion global.
- `!sync prune guild`: elimina todos los slash commands remotos del scope guild configurado.
- `!sync prune global`: elimina todos los slash commands remotos del scope global.
- `!sync prune other`: elimina el scope opuesto al configurado en `BOT_SYNC_SCOPE`, util para limpiar duplicados entre
  `guild` y `global`.
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

El bot escribe logs en consola y en `aa_var/logs/bigness_league.log`.

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
