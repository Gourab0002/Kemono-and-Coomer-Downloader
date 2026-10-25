# Kemono and Coomer Downloader

[![](img/en-flag.svg) English](README.md) | [![](img/br.png) Português](README-ptbr.md)

Baixa posts do [Kemono](https://kemono.cr/) e do [Coomer](https://coomer.st/). Um post, uma lista de posts ou um perfil.

O programa em inglês e o programa em português eram duas cópias do mesmo código. Agora é um programa só. As pastas `codeen` e `codept` apenas escolhem o idioma do menu.

## Instalação

Python 3.10 ou mais novo.

```sh
py -3 -m pip install -r requirements.txt
py -3 main.py
```

`python main.py` também funciona quando `python` está no PATH. Em `codeen`, o menu fica em inglês. Em `codept`, o menu fica em português.

## Menu

1. Baixar um post ou vários. Cole os links separados por vírgula ou espaço, ou informe um arquivo de texto com a mesma lista.
2. Baixar posts de um perfil: todos, uma página, um intervalo de páginas ou os posts entre dois ids.
3. Configurações.
4. Sair.

O offset das páginas sobe de 50 em 50. A primeira página é `0`, a segunda é `50`, a terceira é `100`. Um intervalo aceita esses números ou as palavras `start` e `end`.

```text
https://kemono.cr/patreon/user/USER_ID/post/POST_ID
https://coomer.st/onlyfans/user/USER_ID
```

Domínios antigos, como `kemono.su` e `coomer.party`, são aceitos e enviados para o site atual.

## Comandos

```sh
py -3 main.py post "https://kemono.cr/patreon/user/USER_ID/post/POST_ID"
py -3 main.py post --file links.txt
py -3 main.py profile "https://kemono.cr/patreon/user/USER_ID"
py -3 main.py profile "https://kemono.cr/patreon/user/USER_ID" --offset 50
py -3 main.py profile "https://kemono.cr/patreon/user/USER_ID" --offset 0-750
py -3 main.py profile "https://kemono.cr/patreon/user/USER_ID" --between 1000 2000
py -3 main.py --lang pt --dir D:\Archive post "https://coomer.st/onlyfans/user/USER_ID/post/POST_ID"
py -3 main.py --layout flat profile "https://coomer.st/onlyfans/user/USER_ID"
```

`--limit 10` para depois de 10 posts. `--dir` escolhe onde as pastas dos sites são criadas. O padrão é a pasta de onde você iniciou o programa. `--layout folders` mantém uma pasta por post. `--layout flat` coloca todos os arquivos na pasta do criador. O menu pergunta isso antes de cada download.

## Configurações

`config/conf.json`:

| Configuração | Padrão | Significado |
|---|---|---|
| `get_empty_posts` | `false` | Downloads de perfil ignoram posts sem arquivos |
| `process_from_oldest` | `false` | Com `true`, baixa o post mais antigo primeiro |
| `save_info` | `true` | Grava `files.md` ou `files.txt` em `kcdl-state` para cada post |
| `separate_folders` | `true` | `true` cria uma pasta por post. `false` coloca todos os arquivos em uma pasta |
| `post_info` | `md` | `md` ou `txt` |
| `language` | `en` | `en` ou `pt` |
| `file_interval` | `1.0` | Segundos entre pedidos de arquivo. O mínimo é 1 |
| `api_interval` | `0.4` | Segundos entre pedidos da API |
| `connect_timeout` | `5` | Segundos para um servidor de arquivos aceitar a conexão |
| `read_timeout` | `120` | Segundos de espera durante a transferência |

Desligar `save_info` só pula o arquivo de informações. Os arquivos do post continuam sendo baixados.

## Onde os arquivos ficam

```text
kemono/ ou coomer/
└── Nome-serviço-userId/
    └── posts/
        └── POST_ID/
            └── 1-arquivo.ext

kcdl-state/
└── kemono/ ou coomer/
    ├── profiles.json
    └── Nome-serviço-userId/
        └── posts/
            └── POST_ID/
                ├── download.json
                └── files.md
```

Com uma pasta só, as imagens ficam direto em `Nome-serviço-userId\`. Se dois posts usariam o mesmo nome de arquivo, o segundo recebe o id do post na frente. O `download.json` e o `files.md` ficam em `kcdl-state`, e não junto das imagens.

`download.json` lembra o que foi salvo. Um arquivo original completo é pulado na próxima execução. Uma prévia é tentada de novo, caso o arquivo completo esteja acessível, e permanece no lugar quando não está.

## Servidores de arquivo

O Kemono e o Coomer guardam o texto do post no site principal. Os arquivos completos ficam nos servidores `n1`–`n4`, e esses servidores muitas vezes não aceitam conexão. Quando isso acontece com um arquivo do Kemono, o programa baixa o mesmo arquivo em `https://file.pawchive.pw`. Esse servidor pede um user agent identificável e no máximo um pedido por segundo. Este programa faz as duas coisas.

Os arquivos do Coomer não estão nesse espelho. Se o servidor de arquivos do Coomer não responde, o programa salva a prévia de `img.coomer.st` e avisa no log. O arquivo de informações marca esse arquivo como prévia.

O user agent é `KemonoCoomerDownloader/2.0 (+https://github.com/e43b/Kemono-and-Coomer-Downloader)`.

## Testes

```sh
py -3 -m unittest discover -s tests
```

## Autor

[E43b](https://github.com/e43b). Dúvidas e bugs: [Discord](https://discord.gg/GNJbxzD8bK). Apoio: [Ko-fi](https://ko-fi.com/e43bs).
