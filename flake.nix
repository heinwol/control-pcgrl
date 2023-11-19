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

        pypkgs-build-requirements = with pkgs; {
          # box2d-py = [ "setuptools" swig4 ];
          atari-py = [ "setuptools" cmake zlib.dev ];
          gym-notices = [ "setuptools" ];
          neat-python = [ "setuptools" ];
          tensorflow-io-gcs-filesystem = [ libtensorflow ];
          gizeh = [ "setuptools" ];
          # numba = [ tbb.dev ];
          # swig = [ "setuptools" "skbuild" ];
          # hydra-core = [ "setuptools" ];
          # pygobject = [ "setuptools" pkg-config cairo gobject-introspection ];
        };

        p2n-overrides = poetry2nixLib.defaultPoetryOverrides.extend (self: super:
          (builtins.mapAttrs
            (package: build-requirements:
              (builtins.getAttr package super).overridePythonAttrs (old: {
                buildInputs = (old.buildInputs or [ ]) ++ (
                  builtins.map
                    (pkg:
                      if builtins.isString pkg
                      then builtins.getAttr pkg super
                      else pkg)
                    build-requirements
                );
              })
            )
            pypkgs-build-requirements)
          // {
            inherit (pkgs.python310Packages)
              pygame hydra-core llvmlite numba numpy pyyaml;
            # dm-tree 
            # swig = pkgs.swig4;
          }
          // {
            # box2d-py = super.box2d-py.overrideAttrs (prev: {
            #   preferWheel = true;
            #   # propagatedBuildInputs = (prev.propagatedBuildInputs or [ ]) ++ [ cmake ];
            #   nativeBuildInputs = (prev.nativeBuildInputs or [ ]) ++ [ ];
            # });
            tensorflow = super.tensorflow.overrideAttrs (prev: {
              preferWheel = false;
            });
          }
        );

        devEnv = (poetry2nixLib.mkPoetryEnv {
          projectDir = self;
          python = pkgs.python310;
          overrides = p2n-overrides;
          preferWheels = true; # I don't want to compile all that
        });
        # }).overrideAttrs (oldAttrs: {
        #   propagatedBuildInputs = (oldAttrs.propagatedBuildInputs or [ ]) ++ buildStuff;
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
