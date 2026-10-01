import { NavLink } from "react-router-dom";
import { useSelector } from "react-redux";

export default function AppShell({ breadcrumb, children }) {
  const user = useSelector((state) => state.auth.user);
  const initials = user?.name
    ? user.name
        .split(/\s+/)
        .map((part) => part[0])
        .join("")
        .slice(0, 2)
        .toUpperCase()
    : "EX";

  return (
    <div className="app-shell">
      <aside className="sidebar">
        <div className="sidebar-brand">VEA</div>
        <nav className="sidebar-nav">
          <NavLink to="/questions" className="sidebar-link active">
            Mark
          </NavLink>
        </nav>
      </aside>
      <div className="main-area">
        <header className="topbar">
          <div className="breadcrumb">{breadcrumb}</div>
          <div className="topbar-actions">
            <span className="status-dot" />
            <span className="status-text">Prototype</span>
            <div className="avatar">{initials}</div>
          </div>
        </header>
        <main className="page-content">{children}</main>
      </div>
    </div>
  );
}
