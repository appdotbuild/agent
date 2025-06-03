{ pkgs ? import <nixpkgs> {} }:

pkgs.mkShell {
  buildInputs = with pkgs; [
    python312
    nodejs_20
    rustc
    cargo
    awscli2
    docker
    zsh
    oh-my-zsh
    git
    black
    
    # Only core Python packages needed for bootstrapping
    (python312.withPackages (ps: with ps; [
      pip
      setuptools
      wheel
    ]))
  ];

  shellHook = ''
    python -m venv .venv
    source .venv/bin/activate

    # Install all dependencies from requirements.txt
    pip install --upgrade pip --quiet
    pip install -r ./agent/requirements.txt --upgrade --quiet
  '';
}