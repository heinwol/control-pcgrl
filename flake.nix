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
        pkgs = import nixpkgs {
          inherit system;
          config.allowUnfree = true;
        };
        # pkgs = nixpkgs.legacyPackages.${system};
        pythonPkgs = pkgs.python310Packages;
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
          tensorflow-io-gcs-filesystem = [
            (pythonPkgs.tensorflow.overrideAttrs { version = "2.13"; }).libtensorflow
          ];
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
            inherit (pythonPkgs)
              # pygame
              # hydra-core
              llvmlite
              numba
              numpy
              pyyaml
              ;

            # dm-tree 
            # swig = pkgs.swig4;
          }
          // {
            # box2d-py = super.box2d-py.overrideAttrs (prev: {
            #   preferWheel = true;
            #   # propagatedBuildInputs = (prev.propagatedBuildInputs or [ ]) ++ [ cmake ];
            #   nativeBuildInputs = (prev.nativeBuildInputs or [ ]) ++ [ ];
            # });
            # tensorflow = super.tensorflow.overrideAttrs (prev: {
            #   preferWheel = false;
            # });
            pygame = pkgs.python310Packages.pygame.overrideAttrs (oldAttrs: {
              version = super.pygame.version;
            });
            # matplotlib = super.matplotlib.overridePythonAttrs (oldAttrs: {
            #   passthru.args.enableTk = true;
            #   enableTk = true;
            #   # passthru = builtins.trace oldAttrs.passthru.args true;
            # });
            # with pkgs.python310Packages;
            # with super;
            # (pkgs.callPackage
            #   pkgs.python310Packages.pygame.override
            #   {
            #     inherit (pkgs.darwin.apple_sdk.frameworks) AppKit;
            #   });
            # super.pygame.overrideAttrs (prev: {
            #   preferWheel = false;
            # });
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

        devEnvPopulated =
          (devEnv.env.overrideAttrs (oldAttrs: rec {
            buildInputs = with pkgs; [
              go-task
              direnv
              # tk.dev
              # pkgs.cudaPackages_12.cudnn
              # tcl
              # tk
              # tk.dev
              # xorg.libX11
              pythonPkgs.tkinter
            ]
            ++ buildStuff;

            LD_LIBRARY_PATH = pkgs.lib.makeLibraryPath [
              # "/usr/local/cuda/lib64"
              # "/usr/local/cuda/extras/CUPTI/lib64"
              pkgs.cudaPackages_12.cudnn
              pkgs.cudaPackages_12.nccl
              pkgs.cudaPackages_12.cudatoolkit
            ];

            PATH = pkgs.lib.makeBinPath [
              # "/usr/local/cuda/"
              pkgs.cudaPackages_12.nccl
              pkgs.cudaPackages_12.cudnn
              pkgs.cudaPackages_12.cudatoolkit
            ];

            shellHook = ''
              export CUDA_PATH=${pkgs.cudaPackages_12.cudatoolkit}
              export LD_LIBRARY_PATH="${LD_LIBRARY_PATH}:/usr/local/cuda/lib64:/usr/local/cuda/extras/CUPTI/lib64:$LD_LIBRARY_PATH"
              export PATH="${PATH}:$PATH"
            '';

          }));

        app = poetry2nixLib.mkPoetryApplication {
          projectDir = self;
        };

      in
      {
        packages = {
          inherit app;
          default = self.packages.${system}.app;
          inherit devEnv;
        };

        devShells = rec {
          simple = pkgs.mkShell {
            packages = with pkgs; [
              (poetry.override { python3 = pkgs.python310; })
              python310
            ]
            ++ buildStuff;
          };
          packaged = devEnvPopulated;
          default = packaged;
          # default = simple;
        };
      });
}
