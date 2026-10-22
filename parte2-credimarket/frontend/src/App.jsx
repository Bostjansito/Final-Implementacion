import { useState } from "react";
import { Navigate, NavLink, Route, Routes, useNavigate } from "react-router-dom";
import { useAuth } from "./auth";
import { Alerta } from "./componentes";
import Catalogo from "./paginas/Catalogo";
import Login from "./paginas/Login";
import MisSolicitudes from "./paginas/MisSolicitudes";
import Perfil from "./paginas/Perfil";
import Registro from "./paginas/Registro";
import AdminClientes from "./paginas/admin/Clientes";
import AdminInventario from "./paginas/admin/Inventario";
import AdminModelo from "./paginas/admin/Modelo";
import AdminPrestamos from "./paginas/admin/Prestamos";
import AdminProductos from "./paginas/admin/Productos";

function Protegida({ rol, children }) {
  const { sesion, usuario } = useAuth();
  if (!sesion) return <Navigate to="/login" replace />;
  if (rol && usuario.rol !== rol) return <Alerta tipo="error">No tiene permisos para ver esta sección.</Alerta>;
  return children;
}

export default function App() {
  const { usuario, esAdmin, esCliente, logout, aviso, setAviso } = useAuth();
  const [menu, setMenu] = useState(false);
  const navigate = useNavigate();
  const enlace = (to, texto) => <NavLink to={to} onClick={() => setMenu(false)}>{texto}</NavLink>;

  return (
    <>
      <header className="barra">
        <div className="barra-contenido">
          <NavLink to="/" className="marca">CrediMarket</NavLink>
          <button className="btn-menu" onClick={() => setMenu(!menu)} aria-label="Menú">☰</button>
          <nav className={menu ? "abierto" : ""}>
            {enlace("/", "Catálogo")}
            {esCliente && enlace("/mis-solicitudes", "Mis solicitudes")}
            {esCliente && enlace("/perfil", "Mi perfil")}
            {esAdmin && enlace("/admin/productos", "Productos")}
            {esAdmin && enlace("/admin/clientes", "Clientes")}
            {esAdmin && enlace("/admin/inventario", "Inventario")}
            {esAdmin && enlace("/admin/prestamos", "Préstamos")}
            {esAdmin && enlace("/admin/modelo", "Modelo")}
            {usuario ? (
              <span className="usuario">
                <span title={usuario.email}>{usuario.email} · {usuario.rol === "ADMIN" ? "Administrador" : "Cliente"}</span>
                <button className="btn btn-secundario btn-pequeno" onClick={() => { logout(); navigate("/login"); }}>
                  Cerrar sesión
                </button>
              </span>
            ) : enlace("/login", "Iniciar sesión")}
          </nav>
        </div>
      </header>
      <main className="contenido">
        <Alerta tipo="aviso" onCerrar={() => setAviso(null)}>{aviso}</Alerta>
        <Routes>
          <Route path="/" element={<Catalogo />} />
          <Route path="/login" element={<Login />} />
          <Route path="/registro" element={<Registro />} />
          <Route path="/mis-solicitudes" element={<Protegida rol="CLIENTE"><MisSolicitudes /></Protegida>} />
          <Route path="/perfil" element={<Protegida rol="CLIENTE"><Perfil /></Protegida>} />
          <Route path="/admin/productos" element={<Protegida rol="ADMIN"><AdminProductos /></Protegida>} />
          <Route path="/admin/clientes" element={<Protegida rol="ADMIN"><AdminClientes /></Protegida>} />
          <Route path="/admin/inventario" element={<Protegida rol="ADMIN"><AdminInventario /></Protegida>} />
          <Route path="/admin/prestamos" element={<Protegida rol="ADMIN"><AdminPrestamos /></Protegida>} />
          <Route path="/admin/modelo" element={<Protegida rol="ADMIN"><AdminModelo /></Protegida>} />
          <Route path="*" element={<Alerta tipo="error">Página no encontrada.</Alerta>} />
        </Routes>
      </main>
    </>
  );
}
