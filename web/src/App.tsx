import { useEffect, useState } from "react";

import { AUTH_REQUIRED_EVENT, getAuthStatus, login, logout } from "@/api";
import { CameraConsole } from "@/components/camera-console/camera-console";
import { LoginScreen } from "@/components/login-screen";

type AuthState = "loading" | "authenticated" | "unauthenticated";

function App() {
  const [authState, setAuthState] = useState<AuthState>("loading");

  useEffect(() => {
    let cancelled = false;

    function checkAuthStatus() {
      getAuthStatus()
        .then(({ authenticated }) => {
          if (!cancelled) {
            setAuthState(authenticated ? "authenticated" : "unauthenticated");
          }
        })
        .catch(() => {
          if (!cancelled) {
            setAuthState("unauthenticated");
          }
        });
    }

    checkAuthStatus();
    const handleAuthRequired = () => setAuthState("unauthenticated");
    window.addEventListener(AUTH_REQUIRED_EVENT, handleAuthRequired);

    return () => {
      cancelled = true;
      window.removeEventListener(AUTH_REQUIRED_EVENT, handleAuthRequired);
    };
  }, []);

  if (authState === "loading") {
    return (
      <main className="login-shell" aria-label="Checking session">
        <span className="connecting-mark" aria-hidden="true" />
      </main>
    );
  }

  if (authState === "unauthenticated") {
    return (
      <LoginScreen
        onLogin={async (password) => {
          await login(password);
          setAuthState("authenticated");
        }}
      />
    );
  }

  return (
    <CameraConsole
      onLogout={async () => {
        try {
          await logout();
        } finally {
          setAuthState("unauthenticated");
        }
      }}
    />
  );
}

export default App;
