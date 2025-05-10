import { Button } from '@/components/ui/button';
import { stackClientApp } from '@/neon-auth';

function App() {
  return (
    <div className="flex flex-col items-center justify-center min-h-svh">
      <Button onClick={() => {
        const url = stackClientApp.urls.signUp;
        window.location.href = url;
      }}>Sign Up</Button>
    </div>
  );
}

export default App;
