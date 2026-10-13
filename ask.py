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
            ref = s["source"]
            if s.get("clausula"):
                ref += f" · {s['clausula']} {s.get('titulo') or ''}"
            if s.get("pagina"):
                ref += f" · pág. {s['pagina']}"
            print(f"  - {ref}")
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
