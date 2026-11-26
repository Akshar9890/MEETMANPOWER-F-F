from kesari_jefs.services.jefs_core import seed_defaults


def after_install():
	seed_defaults()


def after_migrate():
	seed_defaults()
