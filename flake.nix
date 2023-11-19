{
  description = "Application packaged using poetry2nix";

  inputs = {
    flake-utils.url = "github:numtide/flake-utils";
    nixpkgs.url = "github:NixOS/nixpkgs/nixos-unstable";
    poetry2nix = {
      url = "github:nix-community/poetry2nix";
      inputs.nixpkgs.follows = "nixpkgs";
    };
  };

  outputs = { self, nixpkgs, flake-utils, poetry2nix }:
    flake-utils.lib.eachDefaultSystem (system:
      let
        # see https://github.com/nix-community/poetry2nix/tree/master#api for more functions and examples.
        pkgs = nixpkgs.legacyPackages.${system};
        # inherit (poetry2nix.lib.mkPoetry2Nix { inherit pkgs; }) mkPoetryApplication;
        poetry2nixLib = (poetry2nix.lib.mkPoetry2Nix { inherit pkgs; });

        buildStuff = with pkgs; [
          swig4 # to build box2d-py
          cmake # to build atari-py
          zlib.dev # to build atari-py
          gcc # to build whatever
          pkg-config # to build pygobject
          cairo # -//-
          gobject-introspection # -//-
        ];

        devEnv = (poetry2nixLib.mkPoetryEnv {
          projectDir = self;
          python = pkgs.python310;
        });
        # }).overrideAttrs (oldAttrs: {
        #   # propagatedBuildInputs = (oldAttrs.propagatedBuildInputs or [ ]) ++ buildStuff;
        # });

        app = poetry2nixLib.mkPoetryApplication { projectDir = self; };

      in
      {
        packages = {
          inherit app;
          default = self.packages.${system}.app;
          inherit devEnv;
        };

        devShells.default = pkgs.mkShell {
          packages = with pkgs; [
            (poetry.override { python3 = pkgs.python310; })
            python310
          ]
          ++ buildStuff;
        };
      });
}
