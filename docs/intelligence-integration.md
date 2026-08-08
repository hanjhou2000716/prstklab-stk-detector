# Intelligence integration

The production context composer now calls the existing Market Impact Graph and
Macro Surprise Engine. It keeps transmission paths conditional and returns
`observation_only` when no fresh market synchronisation is available. Missing
macro expectations are not imputed, and the advice gate remains conservative.
