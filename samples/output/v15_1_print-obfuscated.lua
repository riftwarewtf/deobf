-- Deobfuscated by deobf (dynamic trace)
-- source: v15_1_print-obfuscated.lua
-- Detected obfuscation: Luraph v15.1
-- NOTE: reconstructed from observed behaviour; branches that were not taken
--       during the trace are missing and conditions are only noted in comments.
-- anti-tamper trap functions disabled: #7
-- run status: finished
-- 63 statements recorded in 0.68s
-- non-standard globals touched: scratch

-- [deobf] folded 6 repeated calls into 1 helper functions and 0 unrolled runs into loops
Instance.new("Folder")
local ScreenGui = Instance.new("ScreenGui")
local Frame = Instance.new("Frame")
local Path2D = Instance.new("Path2D")
Frame.Parent = ScreenGui
Path2D.Parent = Frame
ScreenGui:Destroy()
task.wait(0)

task.spawn(function()
	task.wait(0)
end)

task.spawn(function()
end)

task.defer(function()
	-- [envlog] cancelled before it ran
end)

task.delay(657, function()
	-- [envlog] cancelled before it ran
end)

local ScreenGui2 = Instance.new("ScreenGui")
local Frame2 = Instance.new("Frame")
Frame2.Position = UDim2.new(0, 0, 0, 0)
Frame2.Size = UDim2.new(0, 231, 0, 240)
Frame2.Parent = ScreenGui2
local Path2D2 = Instance.new("Path2D")
Path2D2.Parent = Frame2
Path2D2:SetControlPoints({ Path2DControlPoint.new(UDim2.new(0.5, 9, 0, -5), UDim2.new(0, 0, 0, 0), UDim2.new(-0.125, -7, -0.0625, 4)), Path2DControlPoint.new(UDim2.new(0, 8, 0, -2), UDim2.new(0.125, 6, 0, 1), UDim2.new(0, 2, 0, 0)), Path2DControlPoint.new(UDim2.new(0.125, -9, 0.1875, -9), UDim2.new(0, 0, 0, -1), UDim2.new(-0.0625, -1, 0, -6)), Path2DControlPoint.new(UDim2.new(0, 7, 0, 2), UDim2.new(0, 7, 0.125, 1), UDim2.new(0, -1, 0, 7)), Path2DControlPoint.new(UDim2.new(0.4375, 4, 0.125, -5), UDim2.new(0.125, -5, -0.125, -6), UDim2.new(0, 0, 0, 0)) })
Path2D2:GetLength()
Path2D2:GetPositionOnCurve(0.53846156597137451)
Path2D2:GetPositionOnCurve(0.61538463830947876)
Path2D2:GetTangentOnCurve(0.4285714328289032)
Path2D2:GetTangentOnCurve(0.25)
Path2D2:GetTangentOnCurve(0.625)
Path2D2:GetTangentOnCurve(0.090909093618392944)
Path2D2:GetPositionOnCurveArcLength(0.78571426868438721)
Path2D2:GetPositionOnCurveArcLength(0.8461538553237915)
Path2D2:GetPositionOnCurveArcLength(0.3333333432674408)
Path2D2:GetTangentOnCurveArcLength(0.10000000149011612)
Path2D2:GetTangentOnCurveArcLength(0.77777779102325439)
ScreenGui2:Destroy()

local function onDescendantRemoving(value)
	local connection = value.DescendantRemoving:Connect(function(descendant)
	end)

	connection:Disconnect()
end

onDescendantRemoving(game)
game.DescendantAdded:Wait()
onDescendantRemoving(workspace)
workspace.DescendantAdded:Wait()
local Folder = Instance.new("Folder")
onDescendantRemoving(Folder)
Folder.DescendantAdded:Wait()
Color3.new(0.63075053691864014, 0.21544045209884644, 0.74417603015899658):WaitForChild(338582479)
Folder:GetChildren()
Folder:Destroy()
local Folder2 = Instance.new("Folder", Folder)
onDescendantRemoving(Folder2)
Folder2.DescendantAdded:Wait()
Folder2.Name = "656759991"
Folder:WaitForChild("656759991")
Folder:Destroy()
Folder2:Destroy()
local HttpService = game:GetService("HttpService")
onDescendantRemoving(HttpService)
HttpService.DescendantAdded:Wait()
local RunService = game:GetService("RunService")
onDescendantRemoving(RunService)
RunService.DescendantAdded:Wait()
