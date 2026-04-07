import _sqlite3, sys
print(_sqlite3.__file__)
print(hasattr(_sqlite3, 'version'))
print([k for k in dir(_sqlite3) if k.startswith('version')])
