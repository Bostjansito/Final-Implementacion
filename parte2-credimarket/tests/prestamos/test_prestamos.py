"""Pruebas unitarias de Préstamos (se ejecutan dentro de la imagen del servicio, ver scripts/pruebas_unitarias.sh)."""
import unittest
from unittest import mock

from app import estados as E
from app import logica
from credimarket_common.mensajeria import crear_mensaje
from credimarket_ml.variables import cuota_mensual, validar_registro

CLIENTE = {"activo": True, "ingresos_mensuales_cop": 5_000_000, "obligaciones_mensuales_cop": 500_000,
           "tipo_empleo": "dependiente", "antiguedad_laboral_meses": 24, "meses_historial_crediticio": 60,
           "creditos_previos": 2, "atrasos_previos_30d": 0, "porcentaje_pago_puntual": 95.0}
COTIZACION = {"precio": 1_000_000, "version": 3, "activo": True, "nombre": "X", "cotizado_at": "2026-01-01T00:00:00Z"}


def riesgo(decision: str) -> dict:
    return {"probabilidad_incumplimiento": 0.1 if decision == "BAJO" else 0.9, "decision_riesgo": decision,
            "umbral": 0.25, "model_version": "vT", "run_id": "r"}


class MaquinaDeEstados(unittest.TestCase):
    def test_transiciones_validas(self):
        for origen, destinos in E.TRANSICIONES.items():
            for destino in destinos:
                E.validar_transicion(origen, destino)

    def test_estados_finales_no_cambian(self):
        for final in E.FINALES:
            for destino in E.TRANSICIONES:
                with self.assertRaises(E.TransicionInvalida):
                    E.validar_transicion(final, destino)

    def test_evento_tardio_no_reactiva(self):
        with self.assertRaises(E.TransicionInvalida):
            E.validar_transicion(E.CANCELADA, E.APROBADA)
        with self.assertRaises(E.TransicionInvalida):
            E.validar_transicion(E.CANCELANDO, E.APROBADA)

    def test_estados_obligatorios_presentes(self):
        for e in ("RECHAZADA", "PENDIENTE_INVENTARIO", "APROBADA", "CANCELADA_SIN_STOCK", "COMPLETADA", "CANCELADA"):
            self.assertIn(e, E.TRANSICIONES)


class Evaluacion(unittest.TestCase):
    def evaluar(self, decision="BAJO", cliente=None, cotizacion=None, cantidad=1, plazo=12):
        with mock.patch.object(logica.modelo, "predecir", return_value=riesgo(decision)) as p:
            ev = logica.evaluar(cliente or CLIENTE, cotizacion or COTIZACION, cantidad, plazo)
        return ev, p

    def test_monto_sale_de_la_cotizacion(self):
        ev, _ = self.evaluar(cantidad=2)
        self.assertEqual(ev["monto"], 2_000_000)
        self.assertEqual(ev["version_producto"], 3)

    def test_favorable_queda_pendiente_de_inventario(self):
        ev, _ = self.evaluar("BAJO")
        self.assertEqual(ev["estado"], E.PENDIENTE_INVENTARIO)

    def test_riesgo_alto_rechaza(self):
        ev, _ = self.evaluar("ALTO")
        self.assertEqual(ev["estado"], E.RECHAZADA)
        self.assertTrue(ev["motivo"].startswith("RIESGO_ALTO"))

    def test_cliente_inactivo_rechaza_sin_modelo(self):
        ev, p = self.evaluar(cliente={**CLIENTE, "activo": False})
        self.assertEqual(ev["estado"], E.RECHAZADA)
        p.assert_not_called()

    def test_informacion_insuficiente(self):
        ev, p = self.evaluar(cliente={**CLIENTE, "ingresos_mensuales_cop": None})
        self.assertIn("INFORMACION_INSUFICIENTE", ev["motivo"])
        p.assert_not_called()

    def test_monto_fuera_de_rango(self):
        ev, _ = self.evaluar(cotizacion={**COTIZACION, "precio": 9_000_000}, cantidad=2)
        self.assertIn("MONTO_FUERA_DE_RANGO", ev["motivo"])

    def test_producto_inactivo(self):
        ev, _ = self.evaluar(cotizacion={**COTIZACION, "activo": False})
        self.assertIn("PRODUCTO_NO_DISPONIBLE", ev["motivo"])

    def test_capacidad_de_pago(self):
        ev, _ = self.evaluar(cliente={**CLIENTE, "obligaciones_mensuales_cop": 4_500_000})
        self.assertIn("CAPACIDAD_DE_PAGO", ev["motivo"])


class Contratos(unittest.TestCase):
    def test_sobre_del_mensaje(self):
        m = crear_mensaje("ReservaSolicitada", "p1", "c1", {"producto_id": "x", "cantidad": 1})
        for campo in ("event_id", "type", "schema_version", "occurred_at", "correlation_id", "prestamo_id", "payload"):
            self.assertIn(campo, m)
        self.assertNotEqual(m["event_id"], crear_mensaje("X", "p", "c", {})["event_id"])

    def test_cuota_formula_del_historico(self):
        # Fila SOL-0000001 del histórico: monto 7.464.000, 6 meses -> cuota 1.323.536,90
        self.assertAlmostEqual(float(cuota_mensual(7_464_000, 6)), 1_323_536.90, delta=0.01)

    def test_validacion_de_entradas(self):
        ok = {k: CLIENTE[k] for k in CLIENTE if k != "activo"} | {"monto_solicitado_cop": 1_000_000, "plazo_meses": 12}
        self.assertEqual(validar_registro(ok), [])
        self.assertTrue(validar_registro({**ok, "plazo_meses": 7}))
        self.assertTrue(validar_registro({**ok, "tipo_empleo": "astronauta"}))
        self.assertTrue(validar_registro({**ok, "incumplimiento_90d": 1}))


if __name__ == "__main__":
    unittest.main()
