import aiomysql
import logging


def log(sql, args=()):
    logging.info(f'SQL: {sql}')
    logging.info(f'ARGS: {args}')


async def create_pool(**kwargs):
    logging.info('create database connection pool...')
    global __pool
    __pool = await aiomysql.create_pool(
        host=kwargs.get('host', 'localhost'),
        port=kwargs.get('port', 3306),
        user=kwargs['user'],
        password=kwargs['password'],
        db=kwargs['db'],
        charset=kwargs.get('charset', 'utf-8'),
        autocommit=kwargs.get('autocommit', True),
        maxsize=kwargs.get('maxsize', 10),
        minsize=kwargs.get('minsize', 1),
    )


async def select(sql, args, size=None):
    log(sql, args)
    global __pool
    # with (await __pool) as conn:
    # cur = await conn.cursor(aiomysql.DictCursor)
    async with __pool.get() as conn:
        async with conn.cursor(aiomysql.DictCursor) as cur:
            await cur.execute(sql.replace('?', '%s'), args or ())
            if size:
                result = await cur.fetchmany(size)
            else:
                result = await cur.fetchall()
        logging.info(f'rows returned: {len(result)}')
        return result


async def execute(sql, args, autocommit=True):
    log(sql, args)
    global __pool
    async with __pool.get() as conn:
        if not autocommit:
            await conn.begin()
        try:
            async with conn.cursor(aiomysql.DictCursor) as cur:
                await cur.execute(sql.replace('?', '%s'), args)
                affected = cur.rowcount
            if not autocommit:
                await conn.commit()
        except BaseException:
            if not autocommit:
                await conn.rollback()
        return affected


class Field:

    def __init__(self, name, column_type, primary_key, default):
        self.name = name
        self.column_type = column_type
        self.primary_key = primary_key
        self.default = default

    def __str__(self):
        return f'<{self.__class__.__name__}, {self.column_type}: {self.name}>'


class StringField(Field):

    def __init__(self, name=None, primary_key=False, default=None, ddl='varchar(100)'):
        super().__init__(name, ddl, primary_key, default)


class BooleanField(Field):

    def __init__(self, name=None, default=False):
        super().__init__(name, 'boolean', False, default)


class IntegerField(Field):

    def __init__(self, name=None, primary_key=False, default=0):
        super().__init__(name, 'bigint', primary_key, default)


class FloatField(Field):

    def __init__(self, name=None, primary_key=False, default=0.0):
        super().__init__(name, 'real', primary_key, default)


class TextField(Field):

    def __init__(self, name=None, default=False):
        super().__init__(name, 'text', False, default)


def create_args_string(n):
    s = []
    for i in range(n):
        s.append('?')
    return ','.join(s)


class ModelMetaclass(type):

    def __new__(mcs, name, bases, attrs):
        if name == 'Model':
            return super().__new__(mcs, name, bases, attrs)
        tableName = attrs.get('__table__')
        logging.info(f'found model: {name}, (table: {tableName})')
        mappings = dict()
        fields = []
        primaryKey = None
        for k, v in attrs.items():
            if isinstance(v, Field):
                logging.info(f'found mapping: {k} ==> {v}')
                mappings[k] = v
                if v.primary_key:
                    if primaryKey:
                        raise RuntimeError(f'Duplicate primary key for field: {k}')
                    primaryKey = k
                else:
                    fields.append(k)
        if not primaryKey:
            raise RuntimeError(f'Primary key not found!')
        for k in mappings.keys():
            attrs.pop(k)
        escaped_fields = list(map(lambda f: f'`{f}`', fields))
        attrs['__mappings__'] = mappings
        attrs['__table__'] = tableName
        attrs['__primary_key__'] = primaryKey
        attrs['__fields__'] = fields

        attrs['__select__'] = f'select `{primaryKey}`, {",".join(escaped_fields)} from `{tableName}`'
        attrs['__insert__'] = f'insert into `{tableName}` ({",".join(escaped_fields)}, `{primaryKey}`)' \
            f'value {create_args_string(len(escaped_fields) + 1)}'
        attrs['__update__'] = f'update `{tableName}` set {",".join(map(lambda f: f"`{f}`=?", fields))}' \
            f'where `{primaryKey}`=?'
        attrs['__delete__'] = f'delete from `{tableName}` where `{primaryKey}=?`'

        return super().__new__(mcs, name, bases, attrs)


class Model(dict, metaclass=ModelMetaclass):

    def __init__(self, **kwargs):
        super().__init__(**kwargs)

    def __getattr__(self, item):
        try:
            return self[item]
        except KeyError:
            raise AttributeError(f'"Model" object has no attribute {item}')

    def __setattr__(self, key, value):
        self[key] = value

    def getValue(self, key):
        return getattr(self, key, None)

    def getValueOrDefault(self, key):
        value = self.getValue(key)
        if value is None:
            field: Field = self.__mappings__[key]
            if field.default is not None:
                value = field.default() if callable(field) else field.default
                logging.debug(f'using default value for {key}: {str(value)}')
                setattr(self, key, value)
        return value

    @classmethod
    async def find(cls, pk):
        """find object by primary key."""
        result = await select(f'{cls.__select__} where `{cls.__primary_key__}`=?', [pk], 1)
        if len(result) == 0:
            return None
        return cls(**result[0])

    @classmethod
    async def findAll(cls, where=None, args=None, **kwargs):
        """find objects by where clause"""
        sql = [cls.__select__]
        if where:
            sql.append('where')
            sql.append(where)
        if args is None:
            args = []
        orderBy = kwargs.get('orderBy', None)
        if orderBy:
            sql.append('order by')
            sql.append(orderBy)
        limit = kwargs.get('limit', None)
        if limit:
            sql.append('limit')
            if isinstance(limit, int):
                sql.append('?')
                args.append(limit)
            elif isinstance(limit, tuple):
                sql.append('?, ?')
                args.extend(limit)
            else:
                raise ValueError(f'Invalid limit value: {str(limit)}')
        result = await select(' '.join(sql), args)
        return [cls(**r) for r in result]

    @classmethod
    async def findNumber(cls, selectField, where=None, args=None):
        """find number by select and where"""
        sql = [f'select {selectField} _num_ from `{cls.__table__}`']
        if where:
            sql.append('where')
            sql.append(where)
        if args is None:
            args = []
        result = await select(' '.join(sql), args, 1)
        if len(result) == 0:
            return None
        return result[0]['_num_']

    async def save(self):
        args = list(map(self.getValueOrDefault, self.__fields__))
        args.append(self.getValueOrDefault(self.__primary_key__))
        rows = await execute(self.__insert__, args)
        if rows != 1:
            logging.warning(f'failed to insert record: affected rows: {rows}')

    async def update(self):
        args = list(map(self.getValue, self.__fields__))
        args.append(self.getValue(self.__primary_key__))
        rows = await execute(self.__update__, args)
        if rows != 1:
            logging.warning(f'failed to update by primary key: affected rows: {rows}')

    async def remove(self):
        args = [self.getValue(self.__primary_key__)]
        rows = await execute(self.__delete__, args)
        if row != 1:
            logging.warning(f'failed to remove by primary key: affected rows: {rows}')
