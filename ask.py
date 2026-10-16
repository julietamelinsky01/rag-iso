"""Chat por terminal con el RAG.

Uso:
    python ask.py                                  (modo conversación)
    python ask.py "¿Qué pide la cláusula 7.5.3?"   (una sola pregunta)
"""
import sys

from rag.answer import answer


def show(question: str) -> None:
    result = answer(question)
    print("\n" + result["answer"])
    if result["sources"]:
        print("\nFragmentos usados:")
        for s in result["sources"]:
            # Misma referencia que en las citas de la respuesta.
            line = f"  - {s['referencia']}"
            if not s["referencia"].startswith(s["source"]):
                line += f" (archivo: {s['source']})"
            if s.get("tipo") == "historial":
                line += " · historial de cambios"
            print(line)
    print()


def main() -> None:
    if len(sys.argv) > 1:
        show(" ".join(sys.argv[1:]))
        return
    print("RAG de normas ISO — escribí tu pregunta (o 'salir')\n")
    while True:
        try:
            q = input("❓ ").strip()
        except (EOFError, KeyboardInterrupt):
            break
        if q.lower() in {"salir", "exit", "q"}:
            break
        if q:
            show(q)


if __name__ == "__main__":
    main()
