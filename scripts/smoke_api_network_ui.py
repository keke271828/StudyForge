"""Desktop autosave and paired-phone use of the same API routing setting."""
import asyncio
import os

from scripts import smoke_explanation_scope_ui as scope

fixture = scope.fixture
fixture.ai.save_settings({'api_connection_mode': 'system'})
routes = []


def client_factory(*args, **kwargs):
    routes.append({'trust_env': kwargs.get('trust_env', True),
                   'verify_enabled': kwargs.get('verify', True) is not False})
    kwargs['transport'] = fixture.httpx.MockTransport(scope.respond)
    return fixture.original(*args, **kwargs)


fixture.httpx.AsyncClient = client_factory
fixture.case.update(process_id=os.getpid())


@fixture.server.app.get('/__network_test__/routes')
def get_routes():
    return {'routes': routes}


@fixture.server.app.post('/__network_test__/routes/reset')
def reset_routes():
    routes.clear()
    return {'ok': True}


mount = next(route for route in fixture.server.app.routes if getattr(route, 'name', None) == 'web')
fixture.server.app.router.routes.remove(mount)
fixture.server.app.router.routes.append(mount)
if __name__ == '__main__':
    asyncio.run(fixture.main())
