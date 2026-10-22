"""Pruebas unitarias de la validación de la importación CSV (sin base de datos)."""
import unittest

from app.importacion import validar_fila

BASE = {"codigo_externo": "CLI-1", "ingresos_mensuales_cop": "2000000", "obligaciones_mensuales_cop": "300000",
        "tipo_empleo": "dependiente", "antiguedad_laboral_meses": "6.0000", "meses_historial_crediticio": "",
        "creditos_previos": "1", "atrasos_previos_30d": "0", "porcentaje_pago_puntual": ""}


class ValidacionFila(unittest.TestCase):
    def test_fila_valida_con_faltantes_permitidos(self):
        d = validar_fila(BASE)
        self.assertEqual(d["ingresos_mensuales_cop"], 2_000_000)
        self.assertIsNone(d["porcentaje_pago_puntual"])
        self.assertEqual(d["nombre"], "Cliente CLI-1")

    def test_errores(self):
        casos = [
            {"ingresos_mensuales_cop": "-1"},
            {"ingresos_mensuales_cop": ""},
            {"tipo_empleo": "astronauta"},
            {"creditos_previos": "1.5"},
            {"porcentaje_pago_puntual": "120"},
            {"codigo_externo": ""},
            {"email": "sin-arroba"},
        ]
        for cambio in casos:
            with self.subTest(cambio=cambio), self.assertRaises(ValueError):
                validar_fila({**BASE, **cambio})


if __name__ == "__main__":
    unittest.main()
