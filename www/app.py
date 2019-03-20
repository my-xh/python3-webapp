from aiohttp import web
import logging

logging.basicConfig(level=logging.INFO)

routes = web.RouteTableDef()


@routes.get('/')
async def index(request):
    return web.Response(body=b'<h1>Awesome</h1>', content_type='text/html')


app = web.Application()
app.add_routes(routes)
logging.info('server started at http://127.0.0.1:8080')
web.run_app(app, host='127.0.0.1', port=8080)
