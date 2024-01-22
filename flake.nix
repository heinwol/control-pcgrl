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
        pkgs = (import nixpkgs
          {
            inherit system;
            config.allowUnfree = true;
          });
        lib = pkgs.lib;
        traceitN = N: val: lib.debug.traceSeqN N val val;
        # .extend
        # (final: prev: rec {
        #   python310 = prev.python310.override {
        #     packageOverrides = self: super: {
        #       eventlet = super.eventlet.overrideAttrs (old: {
        #         doCheck = false;
        #         doInstallCheck = false;
        #       });
        #     };
        #   };

        #   python310Packages = python310.pkgs;
        # });
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

        cudaPackagesV = pkgs.cudaPackages_12;
        KERNEL_VERSION = "6.5.0";
        nvidia_x11 = (pkgs.linuxPackages.nvidiaPackages.stable.overrideAttrs rec {
          version = "545.23.06";
          name = "nvidia-x11-${version}-${KERNEL_VERSION}";
          src = pkgs.fetchurl {
            url = "https://download.nvidia.com/XFree86/Linux-x86_64/${version}/NVIDIA-Linux-x86_64-${version}.run";
            sha256 = "QTnTKAGfcvKvKHik0BgAemV3PrRqRlM3B9jjZeupCC8=";
          };
        });
        LD_LIBRARY_PATH = pkgs.lib.makeLibraryPath [
          # "/usr/local/cuda/lib64"
          # "/usr/local/cuda/extras/CUPTI/lib64"
          cudaPackagesV.cudnn
          cudaPackagesV.nccl
          cudaPackagesV.cudatoolkit
          cudaPackagesV.libcublas
          nvidia_x11
        ];
        PATH = pkgs.lib.makeBinPath [
          # "/usr/local/cuda/"
          cudaPackagesV.nccl
          cudaPackagesV.cudnn
          cudaPackagesV.cudatoolkit
          cudaPackagesV.libcublas
          nvidia_x11
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
            nvidia-cusparse-cu12 = super.nvidia-cusparse-cu12.overrideAttrs (oldAttrs: {
              autoPatchelfIgnoreMissingDeps = true;
              # (Bytecode collision happens with nvidia-cusolver-cu12.)
              postFixup = ''
                rm -r $out/${self.python.sitePackages}/nvidia/{__pycache__,__init__.py}
              '';
              propagatedBuildInputs = (oldAttrs.propagatedBuildInputs or [ ]) ++ [
                cudaPackagesV.cudatoolkit
                # self.nvidia-cublas-cu12
              ];
            });
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
          // (
            let
              fixNvidiaPackageCollision = pname: {
                ${pname} = super.${pname}.overrideAttrs (oldAttrs: {
                  autoPatchelfIgnoreMissingDeps = true;
                  postFixup = ''
                    rm -r $out/${self.python.sitePackages}/nvidia/{__pycache__,__init__.py}
                  '';
                });
              };
              fixAll = pnames: lib.attrsets.mergeAttrsList (map fixNvidiaPackageCollision pnames);
            in
            (fixAll [
              "nvidia-cuda-cupti-cu12"
              "nvidia-cuda-nvrtc-cu12"
              "nvidia-cuda-runtime-cu12"
              "nvidia-cudnn-cu12"
              "nvidia-cufft-cu12"
              "nvidia-curand-cu12"
              "nvidia-cusolver-cu12"
              "nvidia-nccl-cu12"
              "nvidia-nvtx-cu12"
              "nvidia-nvjitlink-cu12"
            ])
          )
        );

        devEnv = (poetry2nixLib.mkPoetryEnv {
          projectDir = self;
          python = pkgs.python310;
          overrides = p2n-overrides;
          preferWheels = true; # I don't want to compile all that
        });
        # }).overrideAttrs (oldAttrs: (
        #   lib.debug.traceSeqN
        #     1
        #     (
        #       # lib.attrsets.attrNames
        #       # map
        #       # (x: x.name)
        #       lib.id
        #         oldAttrs.name
        #     )
        #     {
        #       buildInputs = (oldAttrs.buildInputs or [ ])
        #         ++ buildStuff
        #         ++ (with pkgs; [
        #         cudaPackages_12.cudatoolkit
        #         cudaPackages_12.cudnn
        #         linuxPackages.nvidia_x11
        #         hello
        #         fdefrferqfrre
        #       ]);
        #     }
        # ));

        devEnvPopulated =
          (devEnv.env.overrideAttrs (oldAttrs: rec {
            buildInputs = with pkgs; [
              go-task
              direnv
              # tk.dev
              # cudaPackages_12.cudatoolkit
              # cudaPackages_12.cudnn
              nvidia_x11
              libGLU
              libGL
              # tcl
              # tk
              # tk.dev
              # xorg.libX11
              pythonPkgs.tkinter
              (poetry.override { python3 = pkgs.python310; })
              fontconfig
              ripgrep
            ]
            ++ buildStuff;

            inherit LD_LIBRARY_PATH PATH;

            # :/usr/local/cuda/lib64:/usr/local/cuda/extras/CUPTI/lib64
            shellHook = ''
              export CUDA_PATH=${cudaPackagesV.cudatoolkit}
              # export CUDA_PATH=/usr/local/cuda-12.3
              export LD_LIBRARY_PATH="${LD_LIBRARY_PATH}:$CUDA_PATH/lib/stubs:$LD_LIBRARY_PATH"
              export PATH="${PATH}:$PATH"
              export EXTRA_LDFLAGS="-L/lib -L${nvidia_x11}/lib"
              # export EXTRA_CCFLAGS="-I/usr/include"
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
        pkgs = pkgs;
      });
}
