import config_default

configs = config_default.configs


class Dict(dict):

    def __init__(self, names=(), values=(), **kwargs):
        super().__init__(**kwargs)
        for k, v in zip(names, values):
            self[k] = v

    def __getattr__(self, item):
        try:
            return self[item]
        except KeyError:
            raise AttributeError(f'Dict object has no attribute {item}')

    def __setattr__(self, key, value):
        self[key] = value


def merge(default, override):
    r = {}
    for k, v in default.items():
        if k in override:
            if isinstance(v, dict):
                merge(v, override[k])
            else:
                r[k] = override[k]
        else:
            r[k] = v

    return r


def toDict(d):
    D = Dict()
    for k, v in d.items():
        D[k] = toDict(v) if isinstance(v, dict) else v
    return D


try:
    import config_override

    configs = merge(configs, config_override.configs)
except ImportError:
    pass

configs = toDict(configs)
