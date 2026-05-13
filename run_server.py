import os

from waitress import serve

from app import app


if __name__ == '__main__':
    host = os.environ.get('NETMASTER_HOST', '0.0.0.0')
    port = int(os.environ.get('NETMASTER_PORT', '8080'))
    threads = int(os.environ.get('NETMASTER_WAITRESS_THREADS', '32'))
    connection_limit = int(os.environ.get('NETMASTER_WAITRESS_CONNECTION_LIMIT', '300'))
    backlog = int(os.environ.get('NETMASTER_WAITRESS_BACKLOG', '256'))

    print(f"服务已启动: http://{host}:{port} (waitress threads={threads})")
    serve(
        app,
        host=host,
        port=port,
        threads=threads,
        connection_limit=connection_limit,
        backlog=backlog,
    )
