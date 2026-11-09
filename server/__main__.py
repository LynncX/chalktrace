"""启动本地 Web 产品入口。"""
import argparse
import uvicorn

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='启动板书拾记本地 Web 服务')
    parser.add_argument('--port', type=int, default=8001)
    args = parser.parse_args()
    uvicorn.run('server.app:app', host='127.0.0.1', port=args.port)
