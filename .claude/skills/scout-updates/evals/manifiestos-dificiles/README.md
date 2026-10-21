Manifiestos con los casos que rompieron `inventario.py` (code-review de `QA-176`). `test_inventario.py` compara su
inventario con `esperado.json`: un formato nuevo se prueba añadiendo aquí un archivo y regenerando, desde la carpeta
de la skill, con
`python3 -c "import json,test_inventario as t;print(json.dumps(t.salida_dificil(),ensure_ascii=False,indent=1))" > evals/manifiestos-dificiles/esperado.json`,
revisando el diff a mano.
