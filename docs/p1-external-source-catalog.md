# External source catalog

The source catalog now distinguishes transport (`gmail`), discovery
(`financialjuice`, GDELT, Reuters) and editorial (`haojiao`, `gooaye`) inputs.
Transport and editorial sources cannot independently trigger a risk alert;
FinancialJuice remains discovery-only and requires corroboration. Missing
observations are reported as `not_scanned`, never as `no_event`.
