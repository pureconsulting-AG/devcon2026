# Kranich – Betrieb

## Deployment

Neue Versionen von Kranich werden nur **mittwochs zwischen 6:00 und 8:00 Uhr** ausgerollt,
weil dann das geringste Sendungsaufkommen herrscht. Die Freigabe erteilt immer
**Tobias Reinhardt** (Teamleitung Betrieb), in Vertretung **Aylin Demir**.

Vor jedem Deployment muss der Smoke-Test laufen: `kranich selftest --quick`.

## Backups

- Vollbackup der Datenbank täglich um **02:30 Uhr**
- Aufbewahrung: 35 Tage, danach automatisch gelöscht
- Speicherort: Objektspeicher `s3://nordlicht-backup/kranich/`
- Wiederherstellung testen wir jedes Quartal am ersten Montag

## Rufbereitschaft

Die Rufbereitschaft wechselt **jeden Freitag um 12:00 Uhr**. Reihenfolge:
Jonas Weber → Aylin Demir → Malte Krüger → wieder von vorn.

Erreichbar ist die Rufbereitschaft über die Nummer **0421 555 7788**.

## Eskalation

1. Rufbereitschaft (Reaktionszeit 15 Minuten)
2. Nach 30 Minuten ohne Lösung: Tobias Reinhardt
3. Bei Ausfall länger als 2 Stunden: Geschäftsführung (Dr. Sabine Voss)
