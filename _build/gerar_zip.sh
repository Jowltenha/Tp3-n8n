#!/usr/bin/env bash
# Gera o pacote de entrega do TP3 (exclui segredos, caches e a pasta _build).
set -euo pipefail
cd "$(dirname "$0")/.."
OUT="joao_barboza_DR4_TP3.zip"
rm -f "$OUT"

pendentes=$(grep -l "PENDENTE\|CONFERIR" exercicio_*.md || true)
if [ -n "$pendentes" ]; then echo "ATENCAO - ainda ha trechos PENDENTE/CONFERIR em:"; echo "$pendentes"; echo; fi

faltando=$(grep -ho 'prints/[a-z0-9_]*\.png' exercicio_*.md | sort -u | while read -r p; do [ -f "$p" ] || echo "$p"; done)
if [ -n "$faltando" ]; then echo "ATENCAO - prints ainda faltando:"; echo "$faltando"; echo; fi

zip -r -q "$OUT" README.md .env.example exercicio_*.md scripts diagramas workflows saidas prints -x '*/__pycache__/*' '*:Zone.Identifier' '*.pyc'
echo "Gerado: $(pwd)/$OUT"
unzip -l "$OUT"
