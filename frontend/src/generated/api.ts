export interface paths {
    "/api/config-schema": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Schema */
        get: operations["schema_api_config_schema_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/config/resolve": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /** Resolve */
        post: operations["resolve_api_config_resolve_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/health": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Health */
        get: operations["health_api_health_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/preflight": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /** Preflight */
        post: operations["preflight_api_preflight_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/presets": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Presets */
        get: operations["presets_api_presets_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/runs": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Runs */
        get: operations["runs_api_runs_get"];
        put?: never;
        /** Start */
        post: operations["start_api_runs_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/runs/{run_id}": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Run */
        get: operations["run_api_runs__run_id__get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/runs/{run_id}/artifacts/{name}": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Artifact */
        get: operations["artifact_api_runs__run_id__artifacts__name__get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/runs/{run_id}/cancel": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /** Cancel */
        post: operations["cancel_api_runs__run_id__cancel_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/runs/{run_id}/frames": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Frames */
        get: operations["frames_api_runs__run_id__frames_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/runs/{run_id}/frames/{index}": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Frame */
        get: operations["frame_api_runs__run_id__frames__index__get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/runs/{run_id}/observables": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Observables */
        get: operations["observables_api_runs__run_id__observables_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/runs/{run_id}/preview": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Preview */
        get: operations["preview_api_runs__run_id__preview_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/runs/{run_id}/screen": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Screen */
        get: operations["screen_api_runs__run_id__screen_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/storage": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Storage */
        get: operations["storage_api_storage_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/units": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Units */
        get: operations["units_api_units_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/validation": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Validation */
        get: operations["validation_api_validation_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
}
export type webhooks = Record<string, never>;
export interface components {
    schemas: {
        /** BoundarySpec */
        BoundarySpec: {
            /**
             * Kind
             * @default periodic
             * @enum {string}
             */
            kind: "periodic" | "cap";
            /**
             * Power
             * @default 4
             */
            power: number;
            /**
             * Strength
             * @default 1
             */
            strength: number;
            /**
             * Width
             * @default 8
             */
            width: number;
        };
        /** BudgetSpec */
        BudgetSpec: {
            /**
             * Max Output Bytes
             * @default 1073741824
             */
            max_output_bytes: number;
            /**
             * Max Points
             * @default 262144
             */
            max_points: number;
            /**
             * Max Snapshots
             * @default 128
             */
            max_snapshots: number;
            /**
             * Max Steps
             * @default 200000
             */
            max_steps: number;
            /**
             * Max Working Bytes
             * @default 536870912
             */
            max_working_bytes: number;
        };
        /** EvidenceFreshness */
        EvidenceFreshness: {
            /** Evidence Path */
            evidence_path: string;
            /** Mismatched Sources */
            mismatched_sources: string[];
            /** Report Sha256 */
            report_sha256: string;
            /** Source Match */
            source_match: boolean | null;
        };
        /** EvidenceRecord */
        EvidenceRecord: {
            /** Check Ids */
            check_ids: string[];
            /** Conditions */
            conditions: {
                [key: string]: unknown;
            };
            /** Configuration Sha256 */
            configuration_sha256: string;
            /** Measured Conditions */
            measured_conditions?: {
                [key: string]: unknown;
            } | null;
            /** Metrics */
            metrics?: {
                [key: string]: unknown;
            } | null;
            /** Reference Configuration Sha256 */
            reference_configuration_sha256?: string | null;
            /** Report Sha256 */
            report_sha256?: string | null;
            /** Scope */
            scope: string;
            /**
             * Status
             * @enum {string}
             */
            status: "report_required" | "checked" | "failed" | "stale";
        };
        /** Frame */
        Frame: {
            /** Axes */
            axes: {
                [key: string]: number[];
            };
            /** Config Sha256 */
            config_sha256?: string | null;
            /** Current Location */
            current_location: string;
            /** Current X */
            current_x: number[] | number[][];
            /** Current Y */
            current_y?: number[] | number[][] | null;
            /** Density */
            density: number[] | number[][];
            /**
             * Density Scale Max
             * @default 0
             */
            density_scale_max: number;
            /**
             * Density Scale Scope
             * @default running_max
             * @enum {string}
             */
            density_scale_scope: "running_max" | "max_across_saved_frames";
            /**
             * Dimension
             * @enum {integer}
             */
            dimension: 1 | 2;
            /** Observables */
            observables: {
                [key: string]: number | null;
            };
            /** Phase */
            phase: number[] | number[][];
            /** Potential */
            potential: number[] | number[][];
            /** Run Id */
            run_id?: string | null;
            screen?: components["schemas"]["ScreenProfile"] | null;
            /** Shape */
            shape: number[];
            /** Step */
            step: number;
            /** Time */
            time: number;
            /** Total Steps */
            total_steps: number;
            validity?: components["schemas"]["MeasurementValidity"] | null;
        };
        /** GridSpec */
        GridSpec: {
            /**
             * Bounds
             * @default [
             *       [
             *         -40,
             *         40
             *       ]
             *     ]
             */
            bounds: [
                number,
                number
            ][];
            /**
             * Points
             * @default [
             *       512
             *     ]
             */
            points: number[];
        };
        /** HTTPValidationError */
        HTTPValidationError: {
            /** Detail */
            detail?: components["schemas"]["ValidationError"][];
        };
        /** MeasurementValidity */
        MeasurementValidity: {
            /**
             * Conditional Status
             * @enum {string}
             */
            conditional_status: "resolved" | "below_reporting_floor" | "numerically_zero";
            /** Initial Norm */
            initial_norm: number;
            /** Reason */
            reason?: string | null;
            /** Reporting Floor */
            reporting_floor: number;
            /** Uncertainty Reason */
            uncertainty_reason?: string | null;
            /** Uncertainty Status */
            uncertainty_status?: ("unavailable" | "boundary_or_nyquist_contaminated" | "localized_line_approximation") | null;
        };
        /** PotentialSpec */
        PotentialSpec: {
            /**
             * Kind
             * @default free
             * @enum {string}
             */
            kind: "free" | "harmonic" | "rectangle" | "gaussian" | "double_barrier" | "double_well" | "slit" | "disk" | "waveguide";
            /** Params */
            params?: {
                [key: string]: unknown;
            };
        };
        /** PresetRecord */
        PresetRecord: {
            config: components["schemas"]["SimulationConfig"];
            /**
             * Dimension
             * @enum {integer}
             */
            dimension: 1 | 2;
            /** Evidence */
            evidence: string;
            evidence_record: components["schemas"]["EvidenceRecord"];
            /** Id */
            id: string;
            /** Limitations */
            limitations: string[];
            /** Name */
            name: string;
            /** Question */
            question: string;
            /** Scientific Question */
            scientific_question: string;
            /** Title */
            title: string;
            /** Validation Status */
            validation_status: string;
        };
        /** RunRecord */
        RunRecord: {
            config: components["schemas"]["SimulationConfig"];
            /** Created At */
            created_at: string;
            /** Error */
            error?: string | null;
            /** Id */
            id: string;
            /** Owner */
            owner?: {
                [key: string]: unknown;
            } | null;
            /**
             * Progress
             * @default 0
             */
            progress: number;
            /**
             * Report Status
             * @default pending
             */
            report_status: string;
            /** Resources */
            resources?: {
                [key: string]: unknown;
            };
            /**
             * Schema Version
             * @default 2
             * @enum {integer}
             */
            schema_version: 1 | 2;
            /**
             * Scientific Status
             * @default pending
             */
            scientific_status: string;
            /**
             * Status
             * @enum {string}
             */
            status: "queued" | "running" | "finalizing" | "completed" | "cancelled" | "failed";
            /** Summary */
            summary?: {
                [key: string]: unknown;
            } | null;
            /** Warnings */
            warnings?: string[];
        } & {
            [key: string]: unknown;
        };
        /** SamplingSpec */
        SamplingSpec: {
            /**
             * Observable Every
             * @default 10
             */
            observable_every: number;
            /** Screen X */
            screen_x?: number | null;
            /**
             * Snapshots
             * @default 81
             */
            snapshots: number;
        };
        /** ScreenProfile */
        ScreenProfile: {
            /** Current Integral */
            current_integral: number[];
            /** Current Location */
            current_location?: string | null;
            /** Definition */
            definition: string;
            /** Density */
            density: number[];
            /** Density X */
            density_x: number;
            /** Quadrature */
            quadrature: string;
            /** Requested X */
            requested_x?: number | null;
            /** Time */
            time: number;
            /** X */
            x: number;
            /** Y */
            y: number[];
        };
        /** SimulationConfig */
        SimulationConfig: {
            boundary?: components["schemas"]["BoundarySpec"];
            budget?: components["schemas"]["BudgetSpec"];
            grid?: components["schemas"]["GridSpec"];
            /**
             * Name
             * @default free-gaussian
             */
            name: string;
            potential?: components["schemas"]["PotentialSpec"];
            sampling?: components["schemas"]["SamplingSpec"];
            /**
             * Schema Version
             * @default 1
             * @constant
             */
            schema_version: 1;
            solver?: components["schemas"]["SolverSpec"];
            state?: components["schemas"]["StateSpec"];
            units?: components["schemas"]["UnitSpec"];
        };
        /** SolverSpec */
        SolverSpec: {
            /**
             * Dt
             * @default 0.02
             */
            dt: number;
            /**
             * Duration
             * @default 2
             */
            duration: number;
            /**
             * Kinetic
             * @default spectral
             * @enum {string}
             */
            kinetic: "spectral" | "fd2";
            /**
             * Method
             * @default strang
             * @enum {string}
             */
            method: "strang" | "cn" | "yoshida4";
        };
        /** StateSpec */
        StateSpec: {
            /**
             * Center
             * @default [
             *       -10
             *     ]
             */
            center: number[];
            /**
             * Kind
             * @default gaussian
             * @enum {string}
             */
            kind: "gaussian" | "sum" | "ho_coherent" | "ho_squeezed" | "eigen_superposition" | "waveguide_mode";
            /**
             * Momentum
             * @default [
             *       2
             *     ]
             */
            momentum: number[];
            /** Params */
            params?: {
                [key: string]: unknown;
            };
            /**
             * Phase
             * @default 0
             */
            phase: number;
            /**
             * Sigma
             * @default [
             *       2
             *     ]
             */
            sigma: number[];
        };
        /** UnitScalesRecord */
        UnitScalesRecord: {
            /** Current Per Fs */
            current_per_fs: number;
            /** Current Per Nm Fs */
            current_per_nm_fs: number;
            /** Density Per Nm */
            density_per_nm: number;
            /** Density Per Nm2 */
            density_per_nm2: number;
            /** Energy Ev */
            energy_ev: number;
            /** Length Nm */
            length_nm: number;
            /**
             * Mass
             * @default electron
             * @constant
             */
            mass: "electron";
            /** Momentum Inverse Nm */
            momentum_inverse_nm: number;
            /** Momentum Si */
            momentum_si: number;
            /**
             * Note
             * @default Display conversions only; numerical core uses hbar=m=1.
             */
            note: string;
            /** Time Fs */
            time_fs: number;
        };
        /** UnitSpec */
        UnitSpec: {
            /**
             * Length Nm
             * @default 1
             */
            length_nm: number;
            /**
             * Mode
             * @default dimensionless
             * @enum {string}
             */
            mode: "dimensionless" | "electron";
        };
        /** ValidationCase */
        ValidationCase: {
            /** Criteria */
            criteria?: {
                [key: string]: unknown;
            };
            /** Evidence */
            evidence: string;
            /** Id */
            id: string;
            /** Metrics */
            metrics?: {
                [key: string]: unknown;
            };
            /** Notes */
            notes?: string[];
            /** Status */
            status: string;
        } & {
            [key: string]: unknown;
        };
        /** ValidationError */
        ValidationError: {
            /** Context */
            ctx?: Record<string, never>;
            /** Input */
            input?: unknown;
            /** Location */
            loc: (string | number)[];
            /** Message */
            msg: string;
            /** Error Type */
            type: string;
        };
        /** ValidationReport */
        ValidationReport: {
            /** Cases */
            cases?: components["schemas"]["ValidationCase"][];
            /** Created Utc */
            created_utc?: string | null;
            freshness?: components["schemas"]["EvidenceFreshness"] | null;
            /** Limitations */
            limitations?: string[];
            /** Note */
            note?: string | null;
            /** Status */
            status: string;
            /**
             * Suite
             * @enum {string}
             */
            suite: "quick" | "full";
            summary?: components["schemas"]["ValidationSummary"] | null;
        } & {
            [key: string]: unknown;
        };
        /** ValidationSummary */
        ValidationSummary: {
            /** Failed */
            failed: number;
            /** Passed */
            passed: number;
            /** Total */
            total: number;
        };
    };
    responses: never;
    parameters: never;
    requestBodies: never;
    headers: never;
    pathItems: never;
}
export type $defs = Record<string, never>;
export interface operations {
    schema_api_config_schema_get: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": unknown;
                };
            };
        };
    };
    resolve_api_config_resolve_post: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["SimulationConfig"];
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["SimulationConfig"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    health_api_health_get: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": unknown;
                };
            };
        };
    };
    preflight_api_preflight_post: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["SimulationConfig"];
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": unknown;
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    presets_api_presets_get: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["PresetRecord"][];
                };
            };
        };
    };
    runs_api_runs_get: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["RunRecord"][];
                };
            };
        };
    };
    start_api_runs_post: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["SimulationConfig"];
            };
        };
        responses: {
            /** @description Successful Response */
            202: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["RunRecord"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    run_api_runs__run_id__get: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                run_id: string;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["RunRecord"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    artifact_api_runs__run_id__artifacts__name__get: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                run_id: string;
                name: string;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": unknown;
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    cancel_api_runs__run_id__cancel_post: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                run_id: string;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["RunRecord"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    frames_api_runs__run_id__frames_get: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                run_id: string;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": unknown;
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    frame_api_runs__run_id__frames__index__get: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                run_id: string;
                index: number;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["Frame"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    observables_api_runs__run_id__observables_get: {
        parameters: {
            query?: {
                max_points?: number;
            };
            header?: never;
            path: {
                run_id: string;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": {
                        [key: string]: number | null;
                    }[];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    preview_api_runs__run_id__preview_get: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                run_id: string;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["Frame"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    screen_api_runs__run_id__screen_get: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                run_id: string;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": unknown;
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    storage_api_storage_get: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": unknown;
                };
            };
        };
    };
    units_api_units_get: {
        parameters: {
            query?: {
                length_nm?: number;
            };
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["UnitScalesRecord"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    validation_api_validation_get: {
        parameters: {
            query?: {
                suite?: string;
            };
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ValidationReport"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
}
