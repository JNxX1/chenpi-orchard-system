def register_blueprints(app):
    from . import (assistant, auth, database, harvest, images, live, main, orchards, plans, plots,
                   reports, results, yields)
    for mod in (auth, main, orchards, plots, plans, images, live, results, yields, harvest, reports,
                assistant, database):
        app.register_blueprint(mod.bp)
