# AGENTS.md

Estas instrucciones están en español porque el proyecto, la lógica de negocio y los textos principales del bot se
mantienen en español.

## Objetivo del proyecto

Este proyecto es un bot de Discord para Bigness League. El código debe mantenerse escalable, testeable y alineado con
una arquitectura Clean Architecture / Hexagonal pragmática.

El objetivo no es solo que los cambios funcionen, sino evitar código espagueti: comandos finos, lógica testeable,
adaptadores aislados, textos localizados, validaciones claras y dependencias entre capas controladas.

## Arquitectura

El proyecto está dividido por capas:

- `presentation`: entrada desde Discord: cogs, comandos, views e interacción con usuarios.
- `application`: casos de uso y reglas de negocio puras: parseo de plantillas, validaciones, tickets, fichajes y flujos
  internos.
- `infrastructure`: adaptadores externos y detalles técnicos: Discord helpers, Google Sheets, generación de imágenes,
  i18n, IA de tickets, etc.
- `core`: configuración, errores comunes, contratos base y utilidades transversales.

Reglas prácticas:

- Los cogs deben orquestar, no contener lógica pesada.
- La lógica reutilizable o de negocio debe moverse a servicios, casos de uso o helpers especializados.
- Evitar archivos gigantes de más de 600 líneas.
- Tender a módulos pequeños, idealmente por debajo de unas 500 líneas cuando tenga sentido.
- No introducir dependencias entre capas sin revisar si rompen la arquitectura.

## Reglas de dependencias

Respetar estas restricciones:

- `core` no debe depender de capas externas.
- `application` no debe depender de `presentation` ni de `infrastructure`.
- `application` no debe depender directamente de Discord, Google Sheets u otros frameworks externos.
- `infrastructure` no debe depender de `presentation`.
- Los adaptadores concretos no deben acoplarse entre sí de forma peligrosa. Por ejemplo, Google Sheets no debería
  depender de Discord.

Si una regla obliga a compartir comportamiento, crear contratos, DTOs, servicios o utilidades en una capa adecuada en
vez de importar desde una capa incorrecta.

## SOLID

Aplicar especialmente:

- Responsabilidad única: evitar clases, funciones o ficheros con demasiadas razones para cambiar.
- Inversión de dependencias: la lógica de aplicación debe depender de abstracciones, no de Discord ni Google
  directamente.
- Abierto/cerrado: añadir nuevos formatos o comportamientos extendiendo parsers/helpers, no añadiendo condicionales
  dispersos en cogs.
- Separación de interfaces: preferir helpers pequeños y específicos para Discord, Sheets, mensajes, parseo, imágenes,
  i18n, etc.

## i18n

Los textos visibles para usuarios deben vivir en:

```text
aa_resources/locales/*.json