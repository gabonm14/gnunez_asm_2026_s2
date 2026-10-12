"""Regenera el avance completo con figuras legibles y tablas del informe."""
import matplotlib.pyplot as plt
if __package__ in (None,''):
    from generacion import generar_todos
    from analisis import analizar_todos,experimentos_fundamentos
    from filtros_temporales import ejecutar_temporal
    from filtrado_espectral import ejecutar_espectral
    from comparacion import ejecutar_comparacion
    from actualizar_informe import actualizar_tablas
else:
    from .generacion import generar_todos
    from .analisis import analizar_todos,experimentos_fundamentos
    from .filtros_temporales import ejecutar_temporal
    from .filtrado_espectral import ejecutar_espectral
    from .comparacion import ejecutar_comparacion
    from .actualizar_informe import actualizar_tablas


def ejecutar_todo():
    with plt.rc_context({'font.size':16,'axes.labelsize':17,'axes.titlesize':14,
                         'xtick.labelsize':14,'ytick.labelsize':14,'legend.fontsize':14,
                         'figure.titlesize':16}):
        casos=generar_todos()
        analizar_todos(casos)
        experimentos_fundamentos()
        ejecutar_temporal(casos)
        ejecutar_espectral(casos)
        ejecutar_comparacion(casos)
        actualizar_tablas()
    return casos


if __name__=='__main__':
    plt.switch_backend('Agg')
    ejecutar_todo()
