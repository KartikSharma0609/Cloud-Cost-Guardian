import importlib
import pkgutil

# Importing each module runs its @register decorator.
# Adding a scanner = dropping a new .py file in this folder. Nothing else to edit.
for _module in pkgutil.iter_modules(__path__):
    importlib.import_module(f"{__name__}.{_module.name}")
