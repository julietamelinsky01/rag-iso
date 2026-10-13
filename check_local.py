from rag.clients import embed, generate

print("Probando embeddings locales...", flush=True)
vector = embed(["Cómo se controlan los documentos"], query=True)[0]
print(f"OK: vector de {len(vector)} dimensiones.", flush=True)

print("Probando respuesta local...", flush=True)
respuesta = generate(
    "Respondé en español en una oración.",
    "Decí que el modelo local está funcionando.",
)
print(respuesta)