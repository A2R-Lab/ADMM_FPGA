`timescale 1ns/1ps

module telemetry_counters (
    input  wire        clk,
    input  wire        resetn,
    input  wire        init_active,
    input  wire        init_done_pulse,
    input  wire        solver_active,
    input  wire        solver_done_pulse,
    input  wire [31:0] solve_ddr_bytes,
    output reg  [31:0] init_cycles,
    output reg  [31:0] solver_cycles,
    output reg  [63:0] ddr_bytes_read
);

    reg [31:0] init_counter;
    reg [31:0] solver_counter;

    always @(posedge clk) begin
        if (!resetn) begin
            init_counter   <= 32'd0;
            solver_counter <= 32'd0;
            init_cycles    <= 32'd0;
            solver_cycles  <= 32'd0;
            ddr_bytes_read <= 64'd0;
        end else begin
            if (init_active) begin
                init_counter <= init_counter + 32'd1;
            end

            if (init_done_pulse) begin
                init_cycles <= init_counter;
            end

            if (solver_active) begin
                solver_counter <= solver_counter + 32'd1;
            end

            if (solver_done_pulse) begin
                solver_cycles  <= solver_counter;
                ddr_bytes_read <= ddr_bytes_read + solve_ddr_bytes;
                solver_counter <= 32'd0;
            end
        end
    end

endmodule
