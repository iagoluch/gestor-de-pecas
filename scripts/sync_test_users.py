"""Comando aposentado após a remoção do acesso ao banco normal."""


def main():
    raise RuntimeError(
        "A cópia direta de usuários do banco normal foi desativada. "
        "O Gestor utiliza somente TEST_DATABASE_URL; futuras identidades devem "
        "chegar pelo mecanismo corporativo definido pela TI."
    )


if __name__ == "__main__":
    main()
