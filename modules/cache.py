import inspect
import asyncio
from functools import wraps


def create_and_store_coroutine(cache, key, coro):
    async def func():
        value = await coro
        cache[key] = value
        return value

    return func()


def create_coroutine(value):
    async def new():
        return value

    return new()


def cache():
    def decorator(func):
        _cache = {}

        def _create_key(args, kwargs):
            def fixed_repr(o):
                if o.__class__.__repr__ is object.__repr__:
                    return ''
                return repr(o)

            key = [f'{func.__module__}.{func.__name__}']
            key.extend(fixed_repr(o) for o in args)

            for k, v in kwargs.items():
                if k == 'new_value':
                    continue

                key.append(fixed_repr(k))
                key.append(fixed_repr(v))

            while '' in key:
                key.remove('')
            return ':'.join(key)

        @wraps(func)
        def wrapper(*args, **kwargs):
            key = _create_key(args, kwargs)
            try:
                value = _cache[key]
            except KeyError:
                value = func(*args, **kwargs)

                if inspect.isawaitable(value):
                    return create_and_store_coroutine(_cache, key, value)

                _cache[key] = value
                return value
            else:
                if asyncio.iscoroutinefunction(func):
                    return create_coroutine(value)

                return value

        def _update(*args, **kwargs):
            try:
                key = _create_key(args, kwargs)
                _cache[key] = kwargs['new_value']
            except KeyError:
                return False
            else:
                return True

        def _invalidate(*args, **kwargs):
            try:
                key = _create_key(args, kwargs)
                del _cache[key]
            except KeyError:
                return False
            else:
                return True

        wrapper.invalidate = _invalidate
        wrapper.cache = _cache
        wrapper.update = _update
        wrapper.invalidate = _invalidate
        return wrapper

    return decorator
